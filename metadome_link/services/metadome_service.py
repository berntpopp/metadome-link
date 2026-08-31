"""Service orchestration for live MetaDome lookups and cached landscapes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from metadome_link.api.models import validate_cached_landscape, validate_polled_landscape
from metadome_link.constants import DATA_CURRENCY_CAVEAT, DEFAULT_PAGE_LIMIT, MAX_BATCH_POSITIONS
from metadome_link.exceptions import (
    InvalidInputError,
    NotFoundError,
    UpstreamSchemaError,
    metadome_build_failure,
)
from metadome_link.identifiers import (
    looks_like_transcript_query,
    normalize_gene_symbol,
    validate_transcript_id,
)
from metadome_link.services.citation import recommended_citation
from metadome_link.services.landscape import slice_positions, validate_landscape_range
from metadome_link.services.landscape_views import (
    compare_positions_view,
    get_domains_view,
    get_meta_domain_view,
    get_position_view,
    get_variant_counts_view,
    resolve_meta_domain_request,
    summarize_intolerant_regions_view,
)
from metadome_link.services.pagination import paginate
from metadome_link.services.resolution import (
    detect_query_type,
    pick_canonical,
    sort_transcripts,
)
from metadome_link.services.selectors import require_complete_range, require_position_xor
from metadome_link.services.shaping import shape_record

if TYPE_CHECKING:
    from metadome_link.api.client import MetaDomeClient
    from metadome_link.cache.store import ResultCache
    from metadome_link.config import ServerSettings

#: Cold-build advisory surfaced when a job is still ``processing``.
_COLD_BUILD_WARNING = (
    "A cold MetaDome build can take up to ~1 hour; poll get_tolerance_landscape "
    "with the given poll_after_s until status is no longer 'processing'."
)


#: In-progress -> ready statuses mapped onto the request handle response.
_READY_STATUS = "SUCCESS"


class MetaDomeService:
    """Orchestrates MetaDome lookups over an async client + on-disk result cache."""

    def __init__(
        self,
        client: MetaDomeClient,
        cache: ResultCache,
        *,
        settings: ServerSettings | None = None,
    ) -> None:
        """Build a service over an injected client, cache, and settings."""
        if settings is None:
            from metadome_link.config import settings as default_settings

            settings = default_settings
        self._client = client
        self._cache = cache
        self._settings = settings
        if cache.data_version != client.data_version:
            raise UpstreamSchemaError(
                "MetaDome service client and result cache use different data profiles.",
                field="data_version",
            )

    # -- lifecycle -------------------------------------------------------------

    @property
    def cache(self) -> ResultCache:
        """The on-disk :class:`ResultCache` (read-only handle for diagnostics)."""
        return self._cache

    @property
    def genome_build(self) -> str:
        return self._client.genome_build

    @property
    def data_version(self) -> str:
        return self._client.data_version

    @property
    def data_versions(self) -> dict[str, str]:
        return self._client.data_versions

    @property
    def data_currency_caveat(self) -> str:
        return self._client.data_currency_caveat

    def _stamp_caveat(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "data_currency_caveat" in payload:
            payload["data_currency_caveat"] = self.data_currency_caveat
        return payload

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def _soft_deadline_s(self) -> float:
        """The soft poll deadline (seconds) for cache-miss landscape fetches."""
        return self._settings.metadome.poll_soft_deadline_s

    def _poll_after_s(self) -> float:
        """Suggested client-side wait before re-polling a building job."""
        return self._settings.metadome.poll_initial_interval_s

    # -- resolution ------------------------------------------------------------

    async def resolve_transcript(self, query: str, *, response_mode: str) -> dict[str, Any]:
        """Resolve a gene symbol or ENST id to transcript candidate(s).

        A bare ``ENST...`` query is validated (``.N`` version required) and echoed
        without an upstream call. A gene symbol is looked up via endpoint 1; the
        candidates are sorted by ``aa_length`` descending and an analyzable
        MANE Select transcript (or longest analyzable protein-coding fallback) is canonical.
        Returns (gene path)::

            {transcript_id?, resolved_from: "gene", gene_name,
             canonical_transcript_id, transcripts: [{gencode_id, aa_length,
             has_protein_data, refseq_ids, canonical}], recommended_citation}

        Returns (id path)::

            {transcript_id, resolved_from: "id", recommended_citation}

        Raises:
            InvalidInputError: A malformed/unversioned ENST id.
            NotFoundError: No transcripts exist for the configured build.
        """
        if detect_query_type(query) == "id" and looks_like_transcript_query(query):
            tid = validate_transcript_id(query)
            payload: dict[str, Any] = {
                "transcript_id": tid,
                "resolved_from": "id",
                "recommended_citation": recommended_citation(transcript_id=tid),
            }
            return shape_record(payload, response_mode)

        gene = normalize_gene_symbol(query)
        transcripts = await self._client.get_transcripts(gene)
        if not transcripts:
            raise NotFoundError(
                f"No {self.genome_build} transcripts for gene '{gene}'.",
                recovery_action="check_input",
                field="query",
            )
        ordered = sort_transcripts(transcripts)
        canonical_id = pick_canonical(ordered)
        rows: list[dict[str, Any]] = []
        for entry in ordered:
            row = dict(entry)
            row["canonical"] = entry.get("gencode_id") == canonical_id
            rows.append(row)
        analyzable = any(bool(entry.get("has_protein_data")) for entry in ordered)
        payload = {
            "resolved_from": "gene",
            "gene_name": gene,
            "canonical_transcript_id": canonical_id,
            "analyzable": analyzable,
            "transcripts": rows,
            "recommended_citation": recommended_citation(gene_name=gene),
        }
        if not analyzable:
            payload["note"] = (
                f"No {gene} transcript in MetaDome ({self.genome_build}) has protein data "
                "(has_protein_data=false for all); MetaDome cannot build a tolerance "
                "landscape for this gene. Do not call request_tolerance_landscape."
            )
        return self._stamp_caveat(shape_record(payload, response_mode))

    # -- async landscape request ----------------------------------------------

    async def request_landscape(self, transcript_id: str, *, response_mode: str) -> dict[str, Any]:
        """Submit a landscape build and report a job handle (endpoints 2 + 3).

        Idempotent: a re-submit of a built/running transcript is a fast no-op.

        Returns::

            {job_id, transcript_id, status: "ready"|"processing", poll_after_s,
             eta_hint, cold_build_warning, recommended_citation}

        Raises:
            InvalidInputError: A malformed/unversioned ENST id (local or 400),
                or a build FAILURE caused by a no-protein-data transcript.
            DataUnavailableError: A non-retryable MetaDome build FAILURE.
        """
        tid = validate_transcript_id(transcript_id)
        await self._client.submit_visualization(tid)
        status = await self._client.get_status(tid)
        if status == "FAILURE":
            raise metadome_build_failure(tid, await self._client.get_error(tid))
        ready = status == _READY_STATUS
        payload: dict[str, Any] = {
            "job_id": tid,
            "transcript_id": tid,
            "status": "ready" if ready else "processing",
            "poll_after_s": self._poll_after_s(),
            "eta_hint": "instant (pre-built)" if ready else "seconds to ~1 hour",
            "cold_build_warning": _COLD_BUILD_WARNING,
            "recommended_citation": recommended_citation(transcript_id=tid),
        }
        return shape_record(payload, response_mode)

    # -- landscape fetch -------------------------------------------------------

    async def get_landscape(
        self,
        transcript_id: str,
        *,
        position_start: int | None = None,
        position_stop: int | None = None,
        limit: int,
        offset: int,
        response_mode: str,
    ) -> dict[str, Any]:
        """Return the (sliced/paginated) tolerance landscape; cache-first.

        On a cache miss, one soft-deadline ``poll_until_ready`` attempt runs:
        ``ready`` caches the landscape and continues (returning the
        gene/domains/``positional_annotation`` payload with a ``pagination``
        block); ``processing`` returns a first-class ``status: "processing"``
        success dict (``poll_after_s`` + ``cold_build_warning``); ``failed``
        raises. See the payload construction below for the exact ready shape.

        Raises:
            InvalidInputError: A malformed/unversioned ENST id, or a build
                FAILURE caused by a no-protein-data transcript.
            DataUnavailableError: A non-retryable MetaDome build FAILURE.
        """
        tid = validate_transcript_id(transcript_id)
        require_complete_range(position_start, position_stop)
        landscape = validate_cached_landscape(self._cache.get_result(tid), tid)
        if landscape is None:
            state, result = await self._client.poll_until_ready(
                tid, soft_deadline_s=self._soft_deadline_s
            )
            if state == "processing":
                return {
                    "status": "processing",
                    "transcript_id": tid,
                    "poll_after_s": self._poll_after_s(),
                    "cold_build_warning": _COLD_BUILD_WARNING,
                    "recommended_citation": recommended_citation(transcript_id=tid),
                }
            if state == "failed":
                raise metadome_build_failure(tid, result)
            # state == "ready"
            landscape = validate_polled_landscape(result, tid)
            self._cache.put_result(tid, landscape)

        validate_landscape_range(landscape, position_start, position_stop)
        if position_start is not None and position_stop is not None:
            entries = slice_positions(landscape, position_start, position_stop)
            page, block = paginate(entries, limit=limit, offset=offset)
        else:
            all_positions = landscape.get("positional_annotation")
            entries = all_positions if isinstance(all_positions, list) else []
            page, block = paginate(entries, limit=limit, offset=offset)

        payload: dict[str, Any] = {
            "transcript_id": landscape.get("transcript_id", tid),
            "gene_name": landscape.get("gene_name"),
            "protein_ac": landscape.get("protein_ac"),
            "refseq_ids": landscape.get("refseq_ids", []),
            "domains": landscape.get("domains", []),
            "positional_annotation": page,
            "pagination": block,
            "data_currency_caveat": DATA_CURRENCY_CAVEAT,
            "recommended_citation": recommended_citation(
                transcript_id=tid, gene_name=landscape.get("gene_name")
            ),
        }
        return self._stamp_caveat(shape_record(payload, response_mode))

    # -- per-position ----------------------------------------------------------

    async def get_position(
        self, transcript_id: str, position: int, *, response_mode: str
    ) -> dict[str, Any]:
        """Return one residue's tolerance + domain + variant-count context.

        Thin delegator over :func:`landscape_views.get_position_view` (see there
        for the exact return shape).

        Raises:
            InvalidInputError: ``position`` is out of range (1-based bounds).
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        return get_position_view(landscape, tid, position, response_mode=response_mode)

    async def get_variant_counts(
        self,
        transcript_id: str,
        *,
        position: int | None = None,
        position_start: int | None = None,
        position_stop: int | None = None,
        source: str = "both",
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
        response_mode: str,
    ) -> dict[str, Any]:
        """Return explicitly-scoped residue and homolog evidence (filtered by ``source``).

        Accepts a single ``position`` OR a ``[position_start, position_stop]``
        range (defaulting to the whole protein when neither is given). The result is
        paginated. Thin delegator over
        :func:`landscape_views.get_variant_counts_view` (see there for the shape).

        Raises:
            InvalidInputError: A bad ``source`` or out-of-range ``position``.
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        if source not in ("both", "gnomad", "clinvar"):
            raise InvalidInputError(
                f"Invalid source {source!r}; expected one of both|gnomad|clinvar.",
                field="source",
            )
        require_position_xor(position, position_start, position_stop)
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        validate_landscape_range(landscape, position_start, position_stop)
        return self._stamp_caveat(
            get_variant_counts_view(
                landscape,
                tid,
                position=position,
                position_start=position_start,
                position_stop=position_stop,
                source=source,
                limit=limit,
                offset=offset,
                response_mode=response_mode,
            )
        )

    async def compare_positions(
        self, transcript_id: str, positions: list[int], *, response_mode: str
    ) -> dict[str, Any]:
        """Return a side-by-side tolerance table for a batch of positions.

        Out-of-range positions get a per-item ``error`` row; the whole batch never
        fails for one bad position. Thin delegator over
        :func:`landscape_views.compare_positions_view` (see there for the shape).

        Raises:
            InvalidInputError: ``positions`` exceeds ``MAX_BATCH_POSITIONS``.
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        if len(positions) > MAX_BATCH_POSITIONS:
            raise InvalidInputError(
                f"Too many positions ({len(positions)}); max is {MAX_BATCH_POSITIONS}.",
                field="positions",
            )
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        return self._stamp_caveat(
            compare_positions_view(landscape, tid, positions, response_mode=response_mode)
        )

    # -- domains & meta-domains ------------------------------------------------

    async def get_domains(self, transcript_id: str, *, response_mode: str) -> dict[str, Any]:
        """Return the landscape's top-level Pfam ``domains[]``.

        Thin delegator over :func:`landscape_views.get_domains_view`.

        Raises:
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        return get_domains_view(landscape, tid, response_mode=response_mode)

    async def get_meta_domain(
        self,
        transcript_id: str,
        position: int,
        *,
        domains: dict[str, list[int]] | None = None,
        limit: int,
        offset: int,
        response_mode: str,
    ) -> dict[str, Any]:
        """Return homologous (meta-domain) variant detail for a residue (endpoint 6).

        When ``domains`` (``{PF: [consensus_pos]}``) is omitted it is derived from
        the cached residue's ``domains`` map. A residue with no meta-domain
        mapping returns empty ``meta_domains`` (not an error). The client call
        stays here; shaping is delegated to
        :func:`landscape_views.get_meta_domain_view` (see there for the shape).

        Raises:
            InvalidInputError: ``position`` is out of range.
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        requested = resolve_meta_domain_request(landscape, position, domains)
        raw: dict[str, Any] = {}
        if requested:
            raw = await self._client.get_metadomain_annotation(tid, position, requested)
        return self._stamp_caveat(
            get_meta_domain_view(
                landscape,
                tid,
                position,
                requested,
                raw,
                limit=limit,
                offset=offset,
                response_mode=response_mode,
            )
        )

    # -- analysis --------------------------------------------------------------

    async def summarize_intolerant_regions(
        self,
        transcript_id: str,
        *,
        threshold: float = 0.5,
        min_run: int = 3,
        top_n: int = 15,
        response_mode: str,
    ) -> dict[str, Any]:
        """Summarise the most intolerant contiguous regions of the landscape.

        Each region is the mean-``sw_dn_ds``-ranked run of consecutive residues
        below ``threshold`` (length >= ``min_run``), annotated with overlapping
        Pfam domain ids and explicitly-scoped variant evidence. Thin delegator over
        :func:`landscape_views.summarize_intolerant_regions_view`.

        Raises:
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        return self._stamp_caveat(
            summarize_intolerant_regions_view(
                landscape,
                tid,
                threshold=threshold,
                min_run=min_run,
                top_n=top_n,
                response_mode=response_mode,
            )
        )

    # -- internals -------------------------------------------------------------

    async def _require_landscape(self, transcript_id: str) -> dict[str, Any]:
        """Return the cached landscape, or attempt one soft poll, else raise."""
        cached = validate_cached_landscape(self._cache.get_result(transcript_id), transcript_id)
        if cached is not None:
            return cached
        state, result = await self._client.poll_until_ready(
            transcript_id, soft_deadline_s=self._soft_deadline_s
        )
        if state == "ready":
            landscape = validate_polled_landscape(result, transcript_id)
            self._cache.put_result(transcript_id, landscape)
            return landscape
        if state == "failed":
            raise metadome_build_failure(transcript_id, result)
        raise NotFoundError(
            f"Tolerance landscape for {transcript_id} is not built yet.",
            recovery_action="switch_tool",
            transcript_id=transcript_id,
            next_commands=[
                {
                    "tool": "request_tolerance_landscape",
                    "arguments": {"transcript_id": transcript_id},
                },
                {
                    "tool": "get_tolerance_landscape",
                    "arguments": {"transcript_id": transcript_id},
                },
            ],
        )
