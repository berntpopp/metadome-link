"""Async HTTP client for the MetaDome web API.

MetaDome (https://stuart.radboudumc.nl/metadome/api) is a fully-open, no-auth
service. It builds per-transcript tolerance landscapes **asynchronously** (a
Celery job, cold builds up to ~1 h), so the workflow is a submit -> poll-status
-> fetch-result split. This client wraps the six endpoints behind typed methods
and normalizes their quirks:

- Endpoint 1 (``/get_transcripts/<gene>``) returns a misspelled ``trancript_ids``
  key and a comma-joined ``refseq_nm_numbers`` string -> normalized to a
  ``refseq_ids`` list. An unknown gene is **HTTP 200 with an empty list**, not an
  error, so :meth:`get_transcripts` returns ``[]`` rather than raising.
- Endpoints 2-6 require a **trailing slash**; endpoint 1 has **none**.
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

from metadome_link.config import ServerSettings
from metadome_link.config import settings as default_settings
from metadome_link.exceptions import (
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UpstreamUnavailableError,
)
from metadome_link.identifiers import validate_transcript_id

if TYPE_CHECKING:
    from metadome_link.config import MetaDomeSettings

#: HTTP statuses worth retrying (rate limit + transient upstream faults).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: Jittered exponential-backoff bounds for retryable HTTP failures.
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 8.0

#: Celery / MetaDome in-progress status values (loop while status is one of these).
_PENDING_STATUSES = frozenset({"PENDING", "SENT", "STARTED", "RECEIVED", "RETRY"})


class _TokenBucket:
    """A simple async token-bucket limiter for upstream politeness.

    Refills at ``rate`` tokens/second up to ``burst`` capacity; :meth:`acquire`
    blocks (cooperatively) until a token is available. A non-positive ``rate``
    disables limiting entirely.
    """

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
        """Build the client.

        Args:
            settings: Optional :class:`ServerSettings` override (defaults to the
                module-level singleton). Only ``settings.metadome`` is consumed.
            client: Optional injected ``httpx.AsyncClient`` (for tests). When
                provided it is reused as-is and **not** closed by :meth:`aclose`.
        """
        resolved = settings if settings is not None else default_settings
        self._cfg: MetaDomeSettings = resolved.metadome
        self._base_url = self._cfg.base_url.rstrip("/")
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

    # -- transport -------------------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Open (once) and return the shared AsyncClient."""
        if self._client is None:
            async with self._connect_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=self._cfg.request_timeout_s,
                        headers={
                            "User-Agent": "metadome-link",
                            "Accept": "application/json",
                        },
                        follow_redirects=True,
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
                response = await client.request(method, url, json=json, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
            if response is not None and response.status_code not in _RETRYABLE_STATUS:
                return response
            if attempt >= self._cfg.max_retries:
                if response is not None:
                    return response
                raise UpstreamUnavailableError(
                    f"MetaDome unreachable after {attempt + 1} attempts: {last_exc}",
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
        """Map a non-2xx response to a typed exception (2xx returns ``None``)."""
        status = response.status_code
        if status < 400:
            return
        if status == 404:
            raise NotFoundError("MetaDome resource not found.")
        if status == 400:
            raise InvalidInputError(
                _extract_error(response) or "MetaDome rejected the request as invalid.",
            )
        if status == 429:
            raise RateLimitedError("MetaDome rate limit hit.", retryable=True)
        raise UpstreamUnavailableError(f"MetaDome upstream error (HTTP {status}).", retryable=True)

    async def _get_json(self, path: str) -> Any:
        """GET ``base_url + path`` and return parsed JSON (status mapped first)."""
        response = await self._send("GET", f"{self._base_url}{path}")
        self._raise_for_status(response)
        return response.json()

    async def _post_json(self, path: str, body: dict[str, Any]) -> Any:
        """POST a JSON body to ``base_url + path`` and return parsed JSON."""
        response = await self._send("POST", f"{self._base_url}{path}", json=body)
        self._raise_for_status(response)
        return response.json()

    # -- endpoints -------------------------------------------------------------

    async def get_transcripts(self, gene: str) -> list[dict[str, Any]]:
        """GET ``/get_transcripts/<gene>`` (endpoint 1, no trailing slash).

        Returns a normalized transcript list (each entry has ``gencode_id``,
        ``aa_length``, ``has_protein_data`` and a ``refseq_ids`` *list* split from
        the upstream ``refseq_nm_numbers`` string). An unknown gene yields an
        empty list (upstream returns HTTP 200 with an empty list, not 404), so
        this method never raises :class:`NotFoundError`.
        """
        # URL-encode the gene segment so metacharacters in a free-text query
        # cannot rewrite the request path (normalize_gene_symbol still upstream).
        body = await self._get_json(f"/get_transcripts/{quote(gene, safe='')}")
        # NOTE: upstream key is the misspelled ``trancript_ids`` (sic).
        raw = body.get("trancript_ids", []) if isinstance(body, dict) else []
        out: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            out.append(
                {
                    "gencode_id": entry.get("gencode_id"),
                    "aa_length": entry.get("aa_length"),
                    "has_protein_data": bool(entry.get("has_protein_data", False)),
                    "refseq_ids": _split_refseq(entry.get("refseq_nm_numbers", "")),
                }
            )
        return out

    async def submit_visualization(self, transcript_id: str) -> str:
        """POST ``/submit_visualization/`` (endpoint 2) and return the echoed id.

        A 400 (e.g. unversioned / malformed transcript id) is mapped to
        :class:`InvalidInputError` by ``_raise_for_status``.
        """
        tid = validate_transcript_id(transcript_id)
        body = await self._post_json("/submit_visualization/", {"transcript_id": tid})
        if isinstance(body, dict):
            echoed = body.get("transcript_id")
            if isinstance(echoed, str):
                return echoed
        return tid

    async def get_status(self, transcript_id: str) -> str:
        """GET ``/status/<transcript_id>/`` (endpoint 3); return the raw status string.

        One of ``PENDING|SENT|STARTED|RECEIVED|RETRY|SUCCESS|FAILURE`` (empty
        string if the upstream body lacks a ``status`` key).
        """
        body = await self._get_json(f"/status/{transcript_id}/")
        if isinstance(body, dict):
            return str(body.get("status", ""))
        return ""

    async def get_result(self, transcript_id: str) -> dict[str, Any]:
        """GET ``/result/<transcript_id>/`` (endpoint 4); return the normalized landscape.

        Every ``positional_annotation[i].ClinVar[].clinvar_ID`` is coerced to a
        ``str``. The ``positional_annotation`` length is left as-is (== protein
        length upstream). A 404 (not built yet) raises :class:`NotFoundError`.
        """
        body = await self._get_json(f"/result/{transcript_id}/")
        if not isinstance(body, dict):
            raise UpstreamUnavailableError("MetaDome result had an unexpected shape.")
        positions = body.get("positional_annotation")
        if isinstance(positions, list):
            for entry in positions:
                if isinstance(entry, dict):
                    _coerce_clinvar_ids(entry.get("ClinVar"))
        return body

    async def get_error(self, transcript_id: str) -> dict[str, Any]:
        """GET ``/error/<transcript_id>/`` (endpoint 5); return the stored error dict."""
        body = await self._get_json(f"/error/{transcript_id}/")
        if isinstance(body, dict):
            return body
        return {"error": str(body)}

    async def get_metadomain_annotation(
        self,
        transcript_id: str,
        protein_position: int,
        requested_domains: dict[str, list[int]],
    ) -> dict[str, Any]:
        """POST ``/get_metadomain_annotation/`` (endpoint 6); coerce ``clinvar_ID`` to str.

        ``requested_domains`` maps a Pfam id to a list of 1-based consensus
        positions (read from ``domains[<PF>].consensus_pos`` of the landscape).
        Every ``pathogenic_variants[].clinvar_ID`` (a ``float`` upstream) is
        coerced to a ``str``.
        """
        tid = validate_transcript_id(transcript_id)
        body = await self._post_json(
            "/get_metadomain_annotation/",
            {
                "transcript_id": tid,
                "protein_position": protein_position,
                "requested_domains": requested_domains,
            },
        )
        if not isinstance(body, dict):
            raise UpstreamUnavailableError("MetaDome metadomain had an unexpected shape.")
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
        """Submit (idempotent) then poll status until terminal or the soft deadline.

        Returns one of three states, never blocking past ``soft_deadline_s``:

        - ``("ready", result_dict)`` -- status reached SUCCESS within the deadline.
        - ``("processing", None)`` -- still building when the deadline elapsed.
        - ``("failed", error_dict)`` -- status reached FAILURE.

        Honours the politeness limiter (via the underlying requests) and an
        interval backoff from ``poll_initial_interval_s`` toward
        ``poll_max_interval_s`` with small jitter.
        """
        tid = validate_transcript_id(transcript_id)
        start = time.monotonic()
        await self.submit_visualization(tid)

        interval = self._cfg.poll_initial_interval_s
        max_interval = self._cfg.poll_max_interval_s
        while True:
            status = await self.get_status(tid)
            if status == "SUCCESS":
                return "ready", await self.get_result(tid)
            if status == "FAILURE":
                return "failed", await self.get_error(tid)
            # status is PENDING/SENT/STARTED/RECEIVED/RETRY (or unknown) -> keep waiting.
            elapsed = time.monotonic() - start
            if elapsed >= soft_deadline_s:
                return "processing", None
            # Sleep, but never overrun the soft deadline.
            jitter = interval * random.uniform(0.0, 0.1)  # noqa: S311
            sleep_for = min(interval + jitter, soft_deadline_s - elapsed)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            if time.monotonic() - start >= soft_deadline_s:
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


def _extract_error(response: httpx.Response) -> str:
    """Best-effort human detail from a MetaDome 400 error body."""
    try:
        body = response.json()
    except Exception:
        return response.text[:200].strip()
    if isinstance(body, dict):
        detail = body.get("error")
        if isinstance(detail, str):
            return detail[:280]
    return ""
