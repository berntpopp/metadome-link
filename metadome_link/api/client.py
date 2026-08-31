"""Async HTTP client for the MetaDome web API.

MetaDome (https://www.metadome.app/metadome/api) is a fully-open, no-auth
service. It builds per-transcript tolerance landscapes **asynchronously** (a
Celery job, cold builds up to ~1 h), so the workflow is a submit -> poll-status
-> fetch-result split. This client wraps the six endpoints behind typed methods
and normalizes their quirks:

- Endpoint 1 (``/get_transcripts/<genome_build>/<gene>``) returns a
  comma-joined ``refseq_nm_numbers`` string -> normalized to a
  ``refseq_ids`` list. An unknown gene is **HTTP 200 with an empty list**, not an
  error, so :meth:`get_transcripts` returns ``[]`` rather than raising.
- POST endpoints require a trailing slash; build-scoped GET endpoints do not.
- Transcript ids must carry the ``.N`` version suffix or ``submit`` returns 400.
- ``clinvar_ID`` is a ``str`` in ``/result/`` but a ``float`` in
  ``/get_metadomain_annotation/`` -> coerced to ``str`` in both.

Reliability layer (lifted/adapted from ``mavedb-link``): one shared
``httpx.AsyncClient``, a token-bucket politeness limiter, and jittered
exponential backoff on 429/5xx/timeouts. Status codes map to the typed
exceptions the MCP envelope classifies:

- 404 -> :class:`NotFoundError`
- 400 -> :class:`InvalidInputError`
- 429 (after retries) -> :class:`RateLimitedError`
- 5xx / timeout / network (after retries) -> :class:`UpstreamUnavailableError`
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from metadome_link.api.models import (
    validate_metadomain_blocks,
    validate_result_document,
    validate_transcript_entries,
)
from metadome_link.api.response import parse_json
from metadome_link.api.url_guard import (
    MAX_REDIRECTS,
    DisallowedURLError,
    build_origin_allowlist,
    make_url_guard,
    read_capped_response,
)
from metadome_link.config import ServerSettings, validate_finite_seconds
from metadome_link.config import settings as default_settings
from metadome_link.constants import data_profile
from metadome_link.exceptions import (
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UpstreamSchemaError,
    UpstreamUnavailableError,
)
from metadome_link.identifiers import require_matching_gene, validate_transcript_id
from metadome_link.services.selectors import validate_meta_domain_request

if TYPE_CHECKING:
    from metadome_link.config import MetaDomeSettings

#: HTTP statuses worth retrying (rate limit + transient upstream faults).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: Jittered exponential-backoff bounds for retryable HTTP failures.
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 8.0

#: Celery / MetaDome in-progress status values (loop while status is one of these).
_PENDING_STATUSES = frozenset({"PENDING", "SENT", "STARTED", "RECEIVED", "RETRY"})
_TERMINAL_STATUSES = frozenset({"SUCCESS", "FAILURE"})


class _TokenBucket:
    """Async token-bucket limiter for upstream politeness."""

    def __init__(self, *, rate: float, burst: int) -> None:
        """Initialise with a refill rate (tokens/s) and burst capacity."""
        self._rate = rate
        self._capacity = float(max(1, burst))
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until one token is available, then consume it."""
        if self._rate <= 0:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                await asyncio.sleep(deficit / self._rate)


class MetaDomeClient:
    """Async client for the public MetaDome web API."""

    def __init__(
        self,
        settings: ServerSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Build the client from optional settings and an injected HTTP client."""
        resolved = settings if settings is not None else default_settings
        self._cfg: MetaDomeSettings = resolved.metadome
        self._base_url = self._cfg.base_url.rstrip("/")
        self._genome_build = self._cfg.genome_build
        profile = data_profile(self._genome_build)
        self._data_version = profile.data_version
        self._data_versions = dict(profile.data_versions)
        self._data_currency_caveat = profile.data_currency_caveat
        # F-10: derive the redirect/destination allowlist from the CONFIGURED base
        # URL host (never hardcoded, so an operator base-URL override still works).
        self._url_guard = make_url_guard(build_origin_allowlist(self._cfg.base_url))
        self._client = client
        self._owns_client = client is None
        self._connect_lock = asyncio.Lock()
        self._limiter = _TokenBucket(
            rate=self._cfg.politeness_rate_per_s,
            burst=self._cfg.politeness_burst,
        )

    @property
    def base_url(self) -> str:
        """The configured upstream base URL (no trailing slash)."""
        return self._base_url

    @property
    def genome_build(self) -> str:
        """The exact configured upstream namespace."""
        return self._genome_build

    @property
    def data_version(self) -> str:
        """The cache/provenance identity for the configured build."""
        return self._data_version

    @property
    def data_versions(self) -> dict[str, str]:
        """Return a copy of the configured build's component provenance."""
        return dict(self._data_versions)

    @property
    def data_currency_caveat(self) -> str:
        """The configured build's historical-data warning."""
        return self._data_currency_caveat

    # -- transport -------------------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Open (once) and return the shared AsyncClient."""
        if self._client is None:
            async with self._connect_lock:
                if self._client is None:
                    # Keep httpx's redirect machinery; the request event-hook
                    # validates EVERY hop (scheme/userinfo/host). max_redirects
                    # bounds the chain (each hop is still guarded).
                    self._client = httpx.AsyncClient(
                        timeout=self._cfg.request_timeout_s,
                        headers={
                            "User-Agent": "metadome-link",
                            "Accept": "application/json",
                        },
                        follow_redirects=True,
                        max_redirects=MAX_REDIRECTS,
                        event_hooks={"request": [self._url_guard]},
                    )
        return self._client

    async def _send(
        self,
        method: str,
        url: str,
        *,
        json: Any | None = None,
    ) -> httpx.Response:
        """Send one request with politeness limiting + jittered retry on faults."""
        client = await self._ensure_client()
        headers = {"Content-Type": "application/json"} if json is not None else None
        delay = _BACKOFF_BASE_SECONDS
        last_exc: Exception | None = None
        for attempt in range(self._cfg.max_retries + 1):
            await self._limiter.acquire()
            response: httpx.Response | None = None
            try:
                # F-10: stream with a hard byte cap. The request event-hook guards
                # every hop; a DisallowedURLError / ResponseTooLargeError is NOT a
                # Timeout/TransportError, so it propagates here WITHOUT retry.
                response = await read_capped_response(
                    client,
                    method,
                    url,
                    max_bytes=self._cfg.max_response_bytes,
                    json=json,
                    headers=headers,
                )
            except httpx.TooManyRedirects:
                raise DisallowedURLError() from None
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
            if response is not None and response.status_code not in _RETRYABLE_STATUS:
                return response
            if attempt >= self._cfg.max_retries:
                if response is not None:
                    return response
                # Do NOT interpolate str(last_exc): a transport/timeout error's
                # text can carry a host/URL or arbitrary detail. Raise a fixed,
                # body-free message (the exception is chained for server-side debug).
                raise UpstreamUnavailableError(
                    f"MetaDome unreachable after {attempt + 1} attempts.",
                    retryable=True,
                ) from last_exc
            # Full jitter de-synchronises concurrent retries.
            await asyncio.sleep(random.uniform(0, min(delay, _BACKOFF_MAX_SECONDS)))  # noqa: S311
            delay = min(delay * 2, _BACKOFF_MAX_SECONDS)
        raise UpstreamUnavailableError(  # pragma: no cover - loop always returns/raises
            "MetaDome retry loop exhausted", retryable=True
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Map non-2xx statuses to fixed, body-free typed exceptions."""
        status = response.status_code
        if status < 400:
            return
        if status == 404:
            raise NotFoundError("MetaDome resource not found.")
        if status == 400:
            raise InvalidInputError("MetaDome rejected the request as invalid.")
        if status == 429:
            raise RateLimitedError("MetaDome rate limit hit.", retryable=True)
        raise UpstreamUnavailableError(f"MetaDome upstream error (HTTP {status}).", retryable=True)

    async def _get_json(self, path: str) -> Any:
        """GET ``base_url + path`` and return parsed JSON (status mapped first)."""
        response = await self._send("GET", f"{self._base_url}{path}")
        self._raise_for_status(response)
        return parse_json(response)

    async def _post_json(self, path: str, body: dict[str, Any]) -> Any:
        """POST a JSON body to ``base_url + path`` and return parsed JSON."""
        response = await self._send("POST", f"{self._base_url}{path}", json=body)
        self._raise_for_status(response)
        return parse_json(response)

    # -- endpoints -------------------------------------------------------------

    async def get_transcripts(self, gene: str) -> list[dict[str, Any]]:
        """GET the build-scoped transcript list and normalize its entries."""
        # URL-encode the gene segment so metacharacters in a free-text query
        # cannot rewrite the request path (normalize_gene_symbol still upstream).
        body = await self._get_json(
            f"/get_transcripts/{quote(self._genome_build, safe='')}/{quote(gene, safe='')}"
        )
        if not isinstance(body, dict) or "transcript_ids" not in body:
            raise UpstreamSchemaError(
                "MetaDome transcript response is missing transcript_ids.",
                field="transcript_ids",
            )
        if body.get("genome_build") != self._genome_build:
            raise UpstreamSchemaError(
                "MetaDome transcript response has an unexpected genome build.",
                field="genome_build",
            )
        raw = body["transcript_ids"]
        entries = validate_transcript_entries(raw)
        require_matching_gene(body.get("gene_name"), gene)
        if isinstance(raw, list) and raw and body.get("gene_name") is None:
            raise UpstreamSchemaError(
                "MetaDome transcript response is missing gene_name.", field="gene_name"
            )
        out: list[dict[str, Any]] = []
        for entry in entries:
            out.append(
                {
                    "gencode_id": entry["gencode_id"],
                    "aa_length": entry["aa_length"],
                    "has_protein_data": entry["has_protein_data"],
                    "mane_transcript_type": entry["mane_transcript_type"],
                    "refseq_ids": _split_refseq(entry["refseq_nm_numbers"]),
                }
            )
        return out

    async def submit_visualization(self, transcript_id: str) -> str:
        """POST ``/submit_visualization/`` (endpoint 2) and return the echoed id.

        A 400 (e.g. unversioned / malformed transcript id) is mapped to
        :class:`InvalidInputError` by ``_raise_for_status``.
        """
        tid = validate_transcript_id(transcript_id)
        body = await self._post_json(
            "/submit_visualization/",
            {"transcript_id": tid, "genome_build": self._genome_build},
        )
        if not isinstance(body, dict) or body.get("transcript_id") != tid:
            raise UpstreamSchemaError(
                "MetaDome submit response has an unexpected transcript id.",
                field="transcript_id",
            )
        if "genome_build" in body and body["genome_build"] != self._genome_build:
            raise UpstreamSchemaError(
                "MetaDome submit response has an unexpected genome build.",
                field="genome_build",
            )
        return tid

    async def get_status(self, transcript_id: str) -> str:
        """GET the build-scoped status and return its validated state."""
        tid = validate_transcript_id(transcript_id)
        body = await self._get_json(f"/status/{self._genome_build}/{tid}")
        status_raw = body.get("status") if isinstance(body, dict) else None
        if not isinstance(status_raw, str):
            raise UpstreamSchemaError(
                "MetaDome status response is missing a valid status.", field="status"
            )
        status = status_raw
        if status not in _PENDING_STATUSES | _TERMINAL_STATUSES:
            raise UpstreamSchemaError(
                "MetaDome status response contains an unknown status.", field="status"
            )
        return status

    async def get_result(self, transcript_id: str) -> dict[str, Any]:
        """GET and validate a complete build-scoped landscape document."""
        tid = validate_transcript_id(transcript_id)
        body = await self._get_json(f"/result/{self._genome_build}/{tid}")
        if not isinstance(body, dict) or body.get("transcript_id") != tid:
            raise UpstreamSchemaError(
                "MetaDome result response has an unexpected transcript id.",
                field="transcript_id",
            )
        result = validate_result_document(body)
        positions = result["positional_annotation"]
        for entry in positions:
            _coerce_clinvar_ids(entry.get("ClinVar"))
        if isinstance(result.get("refseq_ids"), str):
            result["refseq_ids"] = _split_refseq(result["refseq_ids"])
        return result

    async def get_error(self, transcript_id: str) -> dict[str, Any]:
        """GET the stored build-scoped error dictionary."""
        tid = validate_transcript_id(transcript_id)
        body = await self._get_json(f"/error/{self._genome_build}/{tid}")
        if isinstance(body, dict):
            return body
        return {"error": str(body)}

    async def get_metadomain_annotation(
        self,
        transcript_id: str,
        protein_position: int,
        requested_domains: dict[str, list[int]],
    ) -> dict[str, Any]:
        """POST endpoint 6 after validating the finite selector request."""
        tid = validate_transcript_id(transcript_id)
        requested_domains = validate_meta_domain_request(protein_position, requested_domains)
        body = await self._post_json(
            "/get_metadomain_annotation/",
            {
                "transcript_id": tid,
                "genome_build": self._genome_build,
                "protein_position": protein_position,
                "requested_domains": requested_domains,
            },
        )
        if not isinstance(body, dict):
            raise UpstreamUnavailableError("MetaDome metadomain had an unexpected shape.")
        unexpected = set(body) - set(requested_domains)
        if unexpected:
            raise UpstreamUnavailableError(
                "MetaDome metadomain returned an unrequested domain.",
                field=f"metadomain_annotation.{next(iter(unexpected))}",
            )
        validate_metadomain_blocks(body)
        for domain in body.values():
            if isinstance(domain, dict):
                _coerce_clinvar_ids(domain.get("pathogenic_variants"))
        return body

    # -- orchestration ---------------------------------------------------------

    async def poll_until_ready(
        self,
        transcript_id: str,
        *,
        soft_deadline_s: float,
    ) -> tuple[str, dict[str, Any] | None]:
        """Submit and poll until terminal state or the strict soft deadline."""
        tid = validate_transcript_id(transcript_id)
        start = time.monotonic()
        try:
            deadline_seconds = validate_finite_seconds(soft_deadline_s, maximum=3600)
        except ValueError:
            raise InvalidInputError(
                "soft_deadline_s must be a finite value in (0, 3600].",
                field="soft_deadline_s",
            ) from None
        deadline = start + deadline_seconds
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "processing", None
        try:
            await asyncio.wait_for(self.submit_visualization(tid), timeout=remaining)
        except TimeoutError:
            return "processing", None

        interval = self._cfg.poll_initial_interval_s
        max_interval = self._cfg.poll_max_interval_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "processing", None
            try:
                status = await asyncio.wait_for(self.get_status(tid), timeout=remaining)
            except TimeoutError:
                return "processing", None
            if status == "SUCCESS":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "processing", None
                try:
                    result = await asyncio.wait_for(self.get_result(tid), timeout=remaining)
                except TimeoutError:
                    return "processing", None
                return "ready", result
            if status == "FAILURE":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "processing", None
                try:
                    error = await asyncio.wait_for(self.get_error(tid), timeout=remaining)
                except TimeoutError:
                    return "processing", None
                return "failed", error
            # status is PENDING/SENT/STARTED/RECEIVED/RETRY (or unknown) -> keep waiting.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "processing", None
            # Sleep, but never overrun the soft deadline.
            jitter = interval * random.uniform(0.0, 0.1)  # noqa: S311
            sleep_for = min(interval + jitter, remaining)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            if time.monotonic() >= deadline:
                return "processing", None
            interval = min(interval * 1.5, max_interval)

    async def aclose(self) -> None:
        """Close the shared client if this instance owns it (idempotent)."""
        if self._owns_client and self._client is not None:
            client, self._client = self._client, None
            await client.aclose()


def _split_refseq(value: object) -> list[str]:
    """Split the comma+space-joined ``refseq_nm_numbers`` string into a list."""
    if not isinstance(value, str) or not value.strip():
        return []
    return [token.strip() for token in value.split(",") if token.strip()]


def _coerce_clinvar_ids(variants: object) -> None:
    """In-place: coerce each variant's ``clinvar_ID`` to ``str`` (handles str|float)."""
    if not isinstance(variants, list):
        return
    for variant in variants:
        if not isinstance(variant, dict) or "clinvar_ID" not in variant:
            continue
        raw = variant["clinvar_ID"]
        if isinstance(raw, str):
            continue
        if isinstance(raw, float) and raw.is_integer():
            variant["clinvar_ID"] = str(int(raw))
        else:
            variant["clinvar_ID"] = str(raw)
