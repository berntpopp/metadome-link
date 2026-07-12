"""Outbound-destination guard + response byte cap for the MetaDome client (F-10).

The client keeps httpx's redirect machinery (``follow_redirects=True``) — a
manual disable-and-loop would have to re-implement httpx's 301/302/303->GET vs
307/308 method-switch and would silently break the two POST endpoints. Instead a
validating **request** event-hook fires on every outgoing request (including
auto-followed redirect hops) and rejects any URL that is not HTTPS, carries
userinfo, or targets a host outside an allowlist **derived from the configured
MetaDome base URL** (never hardcoded, so an operator base-URL override still
works). A streamed byte cap fails closed on an over-large body — it never
truncates, because a truncated JSON landscape is unparseable.

Both :class:`DisallowedURLError` and :class:`ResponseTooLargeError` are
**non-retryable** and deliberately do NOT subclass ``httpx.TimeoutException`` /
``httpx.TransportError``, so the client's retry loop (``api/client.py``) never
retries them; they subclass :class:`UpstreamUnavailableError` so the MCP envelope
classifies them (``upstream_unavailable``, ``retryable=False``) with a fixed,
body-free message.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from metadome_link.exceptions import UpstreamUnavailableError

#: Maximum redirect hops httpx will follow before erroring (each hop is validated).
MAX_REDIRECTS = 5


class DisallowedURLError(UpstreamUnavailableError):
    """An outbound request/redirect hop targeted a non-allowlisted URL. NON-RETRYABLE."""

    def __init__(self, message: str) -> None:
        """Build a non-retryable, envelope-classified destination-guard error."""
        super().__init__(message, retryable=False, recovery_action="switch_tool")


class ResponseTooLargeError(UpstreamUnavailableError):
    """An upstream response body exceeded the hard byte cap. NON-RETRYABLE."""

    def __init__(self, message: str) -> None:
        """Build a non-retryable, envelope-classified over-cap error."""
        super().__init__(message, retryable=False, recovery_action="switch_tool")


def build_host_allowlist(*base_urls: str) -> frozenset[str]:
    """Derive an exact, case-folded host allowlist from configured base URL(s)."""
    hosts: set[str] = set()
    for url in base_urls:
        host = urlsplit(url).hostname
        if host:
            hosts.add(host.lower())
    return frozenset(hosts)


RequestHook = Callable[[httpx.Request], Awaitable[None]]


def make_url_guard(allowed_hosts: frozenset[str]) -> RequestHook:
    """Build an httpx request event-hook: https + no-userinfo + exact-host only."""

    async def _guard(request: httpx.Request) -> None:
        url = request.url
        if url.scheme != "https":
            raise DisallowedURLError("outbound request must use https")
        if url.username or url.password:
            raise DisallowedURLError("outbound request must not carry userinfo")
        if (url.host or "").lower() not in allowed_hosts:
            raise DisallowedURLError("outbound request host is not allowlisted")

    return _guard


async def read_capped_response(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_bytes: int,
    **kwargs: Any,
) -> httpx.Response:
    """Stream a request, enforce a hard byte cap, return the fully-read response.

    The client's request event-hook validates every hop (incl. redirects) before
    any body is read; :class:`ResponseTooLargeError` aborts a body that exceeds
    ``max_bytes`` before it is decoded/parsed (fail-closed, never truncate). Both
    guard exceptions are non-retryable and are not ``httpx.TransportError``
    subclasses, so the caller's retry loop does not retry them. A transient
    timeout/transport fault still surfaces as its native httpx type (retryable).
    """
    total = 0
    chunks: list[bytes] = []
    async with client.stream(method, url, **kwargs) as response:
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ResponseTooLargeError(f"upstream response exceeded the {max_bytes}-byte cap")
            chunks.append(chunk)
        status_code = response.status_code
        request = response.request
    # Rebuild a fully-read Response from the already-decoded bytes so the caller's
    # status mapping + .json() work unchanged. Response headers are intentionally
    # dropped: nothing downstream reads them, and copying Content-Encoding onto
    # already-decoded bytes would corrupt .content.
    return httpx.Response(status_code=status_code, content=b"".join(chunks), request=request)
