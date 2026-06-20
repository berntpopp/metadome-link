"""MetaDome service orchestration — the logic core of the data plane.

:class:`MetaDomeService` composes the async :class:`MetaDomeClient`, the on-disk
:class:`ResultCache`, and the pure shaping/pagination/citation/landscape helpers
into the per-tool operations the MCP plane exposes. It follows the fleet
contract strictly:

- **Returns plain dicts** — never a ``success``/``_meta`` envelope (the envelope
  is added by ``mcp/envelope.py::run_mcp_tool``). Every record-derived payload
  carries ``recommended_citation``.
- **Raises typed exceptions** (:mod:`metadome_link.exceptions`) on error; it
  never builds an error envelope itself.

Async model: MetaDome builds landscapes asynchronously (cold builds up to ~1 h),
so ``get_landscape`` and the per-position helpers are **cache-first**. On a miss
they do ONE soft-deadline ``poll_until_ready`` attempt; a still-building job is a
first-class ``status: "processing"`` success state (for ``get_landscape``) or a
typed ``not_found`` / not-ready error pointing at request+poll (for the
per-position helpers via :meth:`_require_landscape`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from metadome_link.constants import (
    DATA_CURRENCY_CAVEAT,
    MAX_BATCH_POSITIONS,
)
from metadome_link.exceptions import (
    InvalidInputError,
    NotFoundError,
    UpstreamUnavailableError,
)
from metadome_link.identifiers import (
    looks_like_transcript_query,
    normalize_gene_symbol,
    validate_transcript_id,
)
from metadome_link.services.citation import recommended_citation
from metadome_link.services.landscape import (
    domains_for_position,
    intolerant_runs,
    position_to_entry,
    slice_positions,
    variant_counts_for,
)
from metadome_link.services.pagination import paginate
from metadome_link.services.resolution import (
    detect_query_type,
    pick_canonical,
    sort_transcripts,
)
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
        """Build the service.

        Args:
            client: The async :class:`MetaDomeClient` (injected; respx-mocked in
                tests). The service owns its lifecycle only via :meth:`aclose`.
            cache: The on-disk :class:`ResultCache` for completed landscapes.
            settings: Optional :class:`ServerSettings` override; defaults to the
                module singleton. Only ``settings.metadome`` is consumed here.
        """
        if settings is None:
            from metadome_link.config import settings as default_settings

            settings = default_settings
        self._client = client
        self._cache = cache
        self._settings = settings

    # -- lifecycle -------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying client (idempotent)."""
        await self._client.aclose()

    @property
    def _soft_deadline_s(self) -> float:
        """The soft poll deadline (seconds) for cache-miss landscape fetches."""
        return self._settings.metadome.poll_soft_deadline_s

    def _poll_after_s(self) -> float:
        """Suggested client-side wait before re-polling a building job."""
        return self._settings.metadome.poll_initial_interval_s

    # -- resolution ------------------------------------------------------------

    async def resolve_transcript(
        self, query: str, *, response_mode: str
    ) -> dict[str, Any]:
        """Resolve a gene symbol or ENST id to transcript candidate(s).

        A bare ``ENST...`` query is validated (``.N`` version required) and echoed
        without an upstream call. A gene symbol is looked up via endpoint 1; the
        candidates are sorted by ``aa_length`` descending and the longest
        protein-coding transcript flagged ``canonical``.

        Returns (gene path)::

            {transcript_id?, resolved_from: "gene", gene_name,
             canonical_transcript_id, transcripts: [{gencode_id, aa_length,
             has_protein_data, refseq_ids, canonical}], recommended_citation}

        Returns (id path)::

            {transcript_id, resolved_from: "id", recommended_citation}

        Raises:
            InvalidInputError: A malformed/unversioned ENST id.
            NotFoundError: No GRCh37 transcripts exist for the gene.
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
                f"No GRCh37 transcripts for gene '{gene}'.",
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
        payload = {
            "resolved_from": "gene",
            "gene_name": gene,
            "canonical_transcript_id": canonical_id,
            "transcripts": rows,
            "recommended_citation": recommended_citation(gene_name=gene),
        }
        return shape_record(payload, response_mode)

    # -- async landscape request ----------------------------------------------

    async def request_landscape(
        self, transcript_id: str, *, response_mode: str
    ) -> dict[str, Any]:
        """Submit a landscape build and report a job handle (endpoints 2 + 3).

        Idempotent: a re-submit of a built/running transcript is a fast no-op.

        Returns::

            {job_id, transcript_id, status: "ready"|"processing", poll_after_s,
             eta_hint, cold_build_warning, recommended_citation}

        Raises:
            InvalidInputError: A malformed/unversioned ENST id (local or 400).
            UpstreamUnavailableError: The build status is ``FAILURE``.
        """
        tid = validate_transcript_id(transcript_id)
        await self._client.submit_visualization(tid)
        status = await self._client.get_status(tid)
        if status == "FAILURE":
            error = await self._client.get_error(tid)
            raise UpstreamUnavailableError(
                f"MetaDome build failed for {tid}: {error.get('error', 'unknown error')}",
                retryable=True,
                transcript_id=tid,
            )
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
        ``ready`` caches the landscape and continues; ``processing`` returns a
        first-class ``status: "processing"`` success dict; ``failed`` raises.

        Returns (processing)::

            {success: True, status: "processing", transcript_id, poll_after_s,
             cold_build_warning, recommended_citation}

        Returns (ready)::

            {transcript_id, gene_name, protein_ac, refseq_ids, domains,
             positional_annotation: [...], pagination: {total, returned, limit,
             offset, truncated, next_offset}, data_currency_caveat,
             recommended_citation}

        Raises:
            InvalidInputError: A malformed/unversioned ENST id.
            UpstreamUnavailableError: The build status is ``FAILURE``.
        """
        tid = validate_transcript_id(transcript_id)
        landscape = self._cache.get_result(tid)
        if landscape is None:
            state, result = await self._client.poll_until_ready(
                tid, soft_deadline_s=self._soft_deadline_s
            )
            if state == "processing":
                return {
                    "success": True,
                    "status": "processing",
                    "transcript_id": tid,
                    "poll_after_s": self._poll_after_s(),
                    "cold_build_warning": _COLD_BUILD_WARNING,
                    "recommended_citation": recommended_citation(transcript_id=tid),
                }
            if state == "failed":
                detail = (result or {}).get("error", "unknown error")
                raise UpstreamUnavailableError(
                    f"MetaDome build failed for {tid}: {detail}",
                    retryable=True,
                    transcript_id=tid,
                )
            # state == "ready"
            landscape = result or {}
            self._cache.put_result(tid, landscape)

        if position_start is not None and position_stop is not None:
            entries = slice_positions(landscape, position_start, position_stop)
            _, block = paginate(entries, limit=len(entries) or 1, offset=0)
            block["total"] = len(entries)
            block["returned"] = len(entries)
            block["truncated"] = False
            block["next_offset"] = None
            page = entries
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
        return shape_record(payload, response_mode)

    # -- per-position ----------------------------------------------------------

    async def get_position(
        self, transcript_id: str, position: int, *, response_mode: str
    ) -> dict[str, Any]:
        """Return one residue's tolerance + domain + variant-count context.

        Returns the cached ``positional_annotation`` entry, augmented with a
        ``counts`` block and ``recommended_citation``::

            {protein_pos, ref_aa, sw_dn_ds, sw_coverage, ..., domains,
             counts: {gnomad, clinvar}, transcript_id, recommended_citation}

        Raises:
            InvalidInputError: ``position`` is out of range (1-based bounds).
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        entry = position_to_entry(landscape, position)
        payload = dict(entry)
        payload["transcript_id"] = tid
        payload["counts"] = variant_counts_for(entry, "both")
        payload["recommended_citation"] = recommended_citation(
            transcript_id=tid, gene_name=landscape.get("gene_name")
        )
        return shape_record(payload, response_mode)

    async def get_variant_counts(
        self,
        transcript_id: str,
        *,
        position: int | None = None,
        position_start: int | None = None,
        position_stop: int | None = None,
        source: str = "both",
        response_mode: str,
    ) -> dict[str, Any]:
        """Return per-position gnomAD/ClinVar counts (filtered by ``source``).

        Accepts a single ``position`` OR a ``[position_start, position_stop]``
        range (defaulting to the whole protein when neither is given). The result
        is paginated.

        Returns::

            {transcript_id, source, positions: [{protein_pos, ref_aa, sw_dn_ds,
             counts: {gnomad?, clinvar?}, clinvar_variants?}], pagination{...},
             data_currency_caveat, recommended_citation}

        Raises:
            InvalidInputError: A bad ``source`` or out-of-range ``position``.
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        if source not in ("both", "gnomad", "clinvar"):
            raise InvalidInputError(
                f"Invalid source {source!r}; expected one of both|gnomad|clinvar.",
                field="source",
            )
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)

        if position is not None:
            entries = [position_to_entry(landscape, position)]
        elif position_start is not None and position_stop is not None:
            entries = slice_positions(landscape, position_start, position_stop)
        else:
            raw = landscape.get("positional_annotation")
            entries = raw if isinstance(raw, list) else []

        rows: list[dict[str, Any]] = []
        for entry in entries:
            row: dict[str, Any] = {
                "protein_pos": entry.get("protein_pos"),
                "ref_aa": entry.get("ref_aa"),
                "sw_dn_ds": entry.get("sw_dn_ds"),
                "counts": variant_counts_for(entry, source),
            }
            if source in ("both", "clinvar"):
                clinvar = entry.get("ClinVar")
                if isinstance(clinvar, list) and clinvar:
                    row["clinvar_variants"] = [_clinvar_row(v) for v in clinvar]
            rows.append(row)

        # A single explicit position is returned whole (no pagination cap).
        page_limit = len(rows) or 1 if position is not None else 200
        page, block = paginate(rows, limit=page_limit, offset=0)
        payload: dict[str, Any] = {
            "transcript_id": tid,
            "source": source,
            "positions": page,
            "pagination": block,
            "data_currency_caveat": DATA_CURRENCY_CAVEAT,
            "recommended_citation": recommended_citation(
                transcript_id=tid, gene_name=landscape.get("gene_name")
            ),
        }
        return shape_record(payload, response_mode)

    async def compare_positions(
        self, transcript_id: str, positions: list[int], *, response_mode: str
    ) -> dict[str, Any]:
        """Return a side-by-side tolerance table for a batch of positions.

        Out-of-range positions get a per-item ``error`` row; the whole batch never
        fails for one bad position.

        Returns::

            {transcript_id, comparison: [{protein_pos, ref_aa, sw_dn_ds, domains,
             counts} | {protein_pos, error}], recommended_citation}

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

        comparison: list[dict[str, Any]] = []
        for pos in positions:
            try:
                entry = position_to_entry(landscape, pos)
            except InvalidInputError as exc:
                comparison.append({"protein_pos": pos, "error": exc.message})
                continue
            comparison.append(
                {
                    "protein_pos": entry.get("protein_pos"),
                    "ref_aa": entry.get("ref_aa"),
                    "sw_dn_ds": entry.get("sw_dn_ds"),
                    "domain_ids": sorted(_domain_ids(entry)),
                    "counts": variant_counts_for(entry, "both"),
                }
            )
        payload: dict[str, Any] = {
            "transcript_id": tid,
            "comparison": comparison,
            "data_currency_caveat": DATA_CURRENCY_CAVEAT,
            "recommended_citation": recommended_citation(
                transcript_id=tid, gene_name=landscape.get("gene_name")
            ),
        }
        return shape_record(payload, response_mode)

    # -- domains & meta-domains ------------------------------------------------

    async def get_domains(
        self, transcript_id: str, *, response_mode: str
    ) -> dict[str, Any]:
        """Return the landscape's top-level Pfam ``domains[]``.

        Returns::

            {transcript_id, gene_name, domains: [{ID, Name, start, stop,
             metadomain, meta_domain_alignment_depth}], recommended_citation}

        Raises:
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        payload: dict[str, Any] = {
            "transcript_id": tid,
            "gene_name": landscape.get("gene_name"),
            "domains": landscape.get("domains", []),
            "recommended_citation": recommended_citation(
                transcript_id=tid, gene_name=landscape.get("gene_name")
            ),
        }
        return shape_record(payload, response_mode)

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
        mapping returns empty ``meta_domains`` (not an error).

        Returns::

            {transcript_id, protein_position, requested_domains,
             meta_domains: {PF: {alignment_depth, normal_variants: [...],
             pathogenic_variants: [...], pagination?}}, data_currency_caveat,
             recommended_citation}

        Raises:
            InvalidInputError: ``position`` is out of range.
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        requested = domains if domains else domains_for_position(landscape, position)

        meta_domains: dict[str, Any] = {}
        if requested:
            raw = await self._client.get_metadomain_annotation(tid, position, requested)
            for pfam_id, block in raw.items():
                if not isinstance(block, dict):
                    continue
                normal = block.get("normal_variants")
                patho = block.get("pathogenic_variants")
                normal_list = normal if isinstance(normal, list) else []
                patho_list = patho if isinstance(patho, list) else []
                normal_page, normal_block = paginate(
                    normal_list, limit=limit, offset=offset
                )
                patho_page, patho_block = paginate(
                    patho_list, limit=limit, offset=offset
                )
                meta_domains[pfam_id] = {
                    "alignment_depth": block.get("alignment_depth"),
                    "normal_variants": normal_page,
                    "pathogenic_variants": patho_page,
                    "pagination": {
                        "normal_variants": normal_block,
                        "pathogenic_variants": patho_block,
                    },
                }

        payload: dict[str, Any] = {
            "transcript_id": tid,
            "protein_position": position,
            "requested_domains": requested,
            "meta_domains": meta_domains,
            "data_currency_caveat": DATA_CURRENCY_CAVEAT,
            "recommended_citation": recommended_citation(
                transcript_id=tid, gene_name=landscape.get("gene_name")
            ),
        }
        return shape_record(payload, response_mode)

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
        Pfam domain ids and aggregate variant counts.

        Returns::

            {transcript_id, gene_name, threshold, min_run, top_n,
             regions: [{start, stop, length, mean_sw_dn_ds, min_sw_dn_ds,
             domains: [PF...], gnomad_variant_count, clinvar_variant_count}],
             recommended_citation}

        Raises:
            NotFoundError: The landscape is not built yet (``switch_tool``).
        """
        tid = validate_transcript_id(transcript_id)
        landscape = await self._require_landscape(tid)
        runs = intolerant_runs(landscape, threshold, min_run, top_n)
        domains = landscape.get("domains")
        domain_spans = domains if isinstance(domains, list) else []

        regions: list[dict[str, Any]] = []
        for run in runs:
            overlapping = sorted(_overlapping_domains(domain_spans, run["start"], run["stop"]))
            gnomad_total, clinvar_total = _region_counts(
                landscape, run["start"], run["stop"]
            )
            regions.append(
                {
                    **run,
                    "domains": overlapping,
                    "gnomad_variant_count": gnomad_total,
                    "clinvar_variant_count": clinvar_total,
                }
            )
        payload: dict[str, Any] = {
            "transcript_id": tid,
            "gene_name": landscape.get("gene_name"),
            "threshold": threshold,
            "min_run": min_run,
            "top_n": top_n,
            "regions": regions,
            "data_currency_caveat": DATA_CURRENCY_CAVEAT,
            "recommended_citation": recommended_citation(
                transcript_id=tid, gene_name=landscape.get("gene_name")
            ),
        }
        return shape_record(payload, response_mode)

    # -- internals -------------------------------------------------------------

    async def _require_landscape(self, transcript_id: str) -> dict[str, Any]:
        """Return the cached landscape, or attempt ONE soft poll, else raise.

        Used by every per-position/domain/summary method. A still-building job
        raises :class:`NotFoundError` (``recovery_action="switch_tool"``) carrying
        ``next_commands`` hints to request + poll the landscape; a ``FAILURE``
        raises :class:`UpstreamUnavailableError`.
        """
        cached = self._cache.get_result(transcript_id)
        if cached is not None:
            return cached
        state, result = await self._client.poll_until_ready(
            transcript_id, soft_deadline_s=self._soft_deadline_s
        )
        if state == "ready":
            landscape = result or {}
            self._cache.put_result(transcript_id, landscape)
            return landscape
        if state == "failed":
            detail = (result or {}).get("error", "unknown error")
            raise UpstreamUnavailableError(
                f"MetaDome build failed for {transcript_id}: {detail}",
                retryable=True,
                transcript_id=transcript_id,
            )
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


def _domain_ids(entry: dict[str, Any]) -> set[str]:
    """Return the set of Pfam ids covering a residue (from its ``domains`` map)."""
    domains = entry.get("domains")
    if isinstance(domains, dict):
        return {str(k) for k in domains}
    return set()


def _overlapping_domains(
    domain_spans: list[dict[str, Any]], start: int, stop: int
) -> set[str]:
    """Return Pfam ids whose ``[start, stop]`` span overlaps ``[start, stop]``."""
    out: set[str] = set()
    for domain in domain_spans:
        d_start = domain.get("start")
        d_stop = domain.get("stop")
        d_id = domain.get("ID")
        if (
            isinstance(d_start, int)
            and isinstance(d_stop, int)
            and isinstance(d_id, str)
            and d_start <= stop
            and d_stop >= start
        ):
            out.add(d_id)
    return out


def _region_counts(
    landscape: dict[str, Any], start: int, stop: int
) -> tuple[int, int]:
    """Sum gnomAD + ClinVar variant counts across the residues of a region."""
    gnomad_total = 0
    clinvar_total = 0
    for entry in slice_positions(landscape, start, stop):
        counts = variant_counts_for(entry, "both")
        gnomad_total += int(counts.get("gnomad", {}).get("variant_count", 0))
        clinvar_total += int(counts.get("clinvar", {}).get("variant_count", 0))
    return gnomad_total, clinvar_total


def _clinvar_row(variant: dict[str, Any]) -> dict[str, Any]:
    """Project a ``/result/`` ClinVar entry + add the NCBI variation URL."""
    row = dict(variant)
    cid = variant.get("clinvar_ID")
    if isinstance(cid, str) and cid:
        row["url"] = f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{cid}/"
    return row
