"""Discovery tools: ``get_server_capabilities`` and ``get_diagnostics``.

Both are fully implemented here (Task 8). They are the cold-start orientation
surface: ``get_server_capabilities`` projects the static discovery contract
(:func:`metadome_link.mcp.capabilities.build_capabilities`) by ``detail`` level,
and ``get_diagnostics`` reports live runtime state (build info, result-cache
stats, metrics snapshot, data versions, capabilities hash) WITHOUT any network
call to MetaDome.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from metadome_link.buildinfo import build_info
from metadome_link.mcp import metrics
from metadome_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from metadome_link.mcp.capabilities import (
    build_capabilities,
    capabilities_version,
)
from metadome_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from metadome_link.mcp.next_commands import cmd
from metadome_link.mcp.service_adapters import get_metadome_service
from metadome_link.mcp.tools._common import ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: Keys retained for ``detail='summary'`` — the light orientation subset. The
#: heavier prose/policy keys (semantics, provenance, notes, workflows detail) are
#: only emitted for ``detail='full'``.
_SUMMARY_KEYS: tuple[str, ...] = (
    "server",
    "server_version",
    "build",
    "capabilities_version",
    "data_versions",
    "genome_build",
    "data_version",
    "data_source",
    "research_use_only",
    "recommended_citation",
    "license",
    "tools",
    "tool_count",
    "response_modes",
    "default_response_mode",
    "error_codes",
    "limits",
    "read_only",
)


def _project_capabilities(detail: str) -> dict[str, Any]:
    """Return the full contract, or the light summary subset (default)."""
    full = build_capabilities()
    if detail == "full":
        full["detail"] = "full"
        return full
    summary: dict[str, Any] = {k: full[k] for k in _SUMMARY_KEYS if k in full}
    summary["detail"] = "summary"
    summary["more"] = (
        "Call get_server_capabilities(detail='full') or read metadome://capabilities "
        "for recommended workflows, score/async semantics, and policy notes."
    )
    return summary


def register_discovery_tools(mcp: FastMCP) -> None:
    """Register the discovery tools on a FastMCP instance."""

    @mcp.tool(
        name="get_server_capabilities",
        title="Get Server Capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"discovery"},
        description=(
            "Return the metadome-link discovery surface: identity/build/MetaDome data "
            "version, the frozen tool list, response modes, recommended workflows, the "
            "error taxonomy, and limits. detail='full' adds the score/async semantics "
            "and policy notes. Call this first in a cold session, or read "
            "metadome://capabilities / metadome://tools. "
            "Signature: get_server_capabilities(detail=, response_mode=)."
        ),
    )
    async def get_server_capabilities(
        detail: Annotated[
            Literal["summary", "full"],
            Field(description="summary (default, light) or full (adds semantics + notes)."),
        ] = "summary",
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = _project_capabilities(detail)
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("resolve_transcript", query="TP53"),
                cmd("get_diagnostics"),
            ]
            return payload

        return await run_mcp_tool(
            "get_server_capabilities",
            call,
            context=McpErrorContext("get_server_capabilities", response_mode=response_mode),
        )

    @mcp.tool(
        name="get_diagnostics",
        title="Get MetaDome Diagnostics",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"discovery"},
        description=(
            "Report local runtime health WITHOUT calling MetaDome: build info, "
            "result-cache stats (on-disk + LRU sizes, pinned data version), the runtime "
            "metrics snapshot (request/error counts + latency percentiles), the data "
            "versions, and the capabilities hash. Use this to confirm cache state or "
            "diagnose a misconfigured server. "
            "Signature: get_diagnostics(response_mode=)."
        ),
    )
    async def get_diagnostics(
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload: dict[str, Any] = {
                "build": build_info(),
                "cache_stats": service.cache.stats(),
                "metrics": metrics.snapshot(),
                "data_versions": service.data_versions,
                "capabilities_version": capabilities_version(),
            }
            payload.setdefault("_meta", {})["next_commands"] = [
                cmd("get_server_capabilities"),
                cmd("resolve_transcript", query="TP53"),
            ]
            return payload

        return await run_mcp_tool(
            "get_diagnostics",
            call,
            context=McpErrorContext("get_diagnostics", response_mode=response_mode),
        )
