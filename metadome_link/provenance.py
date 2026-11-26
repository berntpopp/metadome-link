"""Per-request upstream fetch time for the Response-Envelope v1.2 ``retrieved_at``.

A cache that serves a stored upstream answer reports when that answer was
fetched; the MCP envelope reads the oldest such time for the call. A call that
recorded none read MetaDome live during this request and reports its start.
State is one mutable dict bound per tool call, so concurrent reads accumulate
into the same object.
"""

from __future__ import annotations

import contextvars
from datetime import UTC, datetime
from typing import Any

#: Tools that orient a client and return no upstream data: outside the v1.2 rule.
OPS_TOOLS = frozenset({"get_server_capabilities", "get_diagnostics"})

_state: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "metadome_provenance", default=None
)


def utc(moment: datetime | str | None = None) -> str:
    """An RFC 3339 UTC timestamp ending in ``Z`` (now, or a stored ISO time)."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    return (moment or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def begin() -> None:
    """Start a fresh scope (call once at tool entry)."""
    _state.set({"start": utc(), "fetched": []})


def fetched(at: str | None) -> None:
    """Record the fetch time of a cached upstream answer (no-op outside a scope)."""
    state = _state.get()
    if state is not None and at:
        state["fetched"].append(at)


def retrieved_at() -> str:
    """The oldest upstream fetch behind this call, else the call's start."""
    state = _state.get()
    if state is None:
        return utc()
    oldest: str = min(state["fetched"], default=state["start"])
    return oldest


def meta(tool_name: str) -> dict[str, str]:
    """The v1.2 ``_meta`` provenance of a data result (empty for an ops tool)."""
    if tool_name in OPS_TOOLS:
        return {}
    from metadome_link.constants import METADOME_DATA_VERSION

    try:
        from metadome_link.mcp.service_adapters import get_metadome_service

        version = get_metadome_service().data_version
    except Exception:  # before startup: the default profile
        version = METADOME_DATA_VERSION
    return {"source": "metadome", "data_version": version, "retrieved_at": retrieved_at()}
