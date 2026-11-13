"""Discovery tool tests through the real FastMCP facade (Task 8).

These exercise the full MCP path: facade → envelope → discovery tool body →
injected (respx-mocked) service. ``get_diagnostics`` must NOT touch the network.
"""

from __future__ import annotations

from typing import Any


async def test_get_server_capabilities_success(facade: Any, call_tool: Any) -> None:
    """get_server_capabilities returns the frozen contract with versioned _meta."""
    data = await call_tool(facade, "get_server_capabilities", {})
    assert data["success"] is True
    assert data["tool_count"] == 11
    assert len(data["tools"]) == 11
    meta = data["_meta"]
    assert meta["capabilities_version"]
    assert meta["data_versions"]["assembly"] == "GRCh38.p14"


async def test_get_server_capabilities_full_detail(facade: Any, call_tool: Any) -> None:
    """detail='full' surfaces the richer policy/semantics keys."""
    data = await call_tool(facade, "get_server_capabilities", {"detail": "full"})
    assert data["success"] is True
    assert data["detail"] == "full"
    assert "recommended_workflows" in data


async def test_get_diagnostics_reports_cache_stats(facade: Any, call_tool: Any) -> None:
    """get_diagnostics returns cache stats + build/metrics with no exception/network."""
    data = await call_tool(facade, "get_diagnostics", {})
    assert data["success"] is True
    assert "cache_stats" in data
    assert "on_disk" in data["cache_stats"]
    assert "data_version" in data["cache_stats"]
    assert "build" in data
    assert "metrics" in data
    assert data["data_versions"]["assembly"] == "GRCh38.p14"
    assert data["_meta"]["capabilities_version"]


async def test_get_diagnostics_takes_no_parameters(facade: Any) -> None:
    """Contract-Truth: get_diagnostics is zero-arg fleet-wide; no dead response_mode (router#158)."""
    tool = next(t for t in await facade.list_tools() if t.name == "get_diagnostics")
    assert tool.parameters.get("properties", {}) == {}
    assert "response_mode" not in (tool.description or "")


async def test_get_server_capabilities_takes_only_detail(facade: Any) -> None:
    """Contract-Truth: response_mode never shaped the capabilities body, so it is not advertised."""
    tool = next(t for t in await facade.list_tools() if t.name == "get_server_capabilities")
    assert set(tool.parameters.get("properties", {})) == {"detail"}
    assert "response_mode" not in (tool.description or "")


async def test_get_server_capabilities_rejects_response_mode_by_name(
    facade: Any, call_tool: Any
) -> None:
    """A legacy caller still sending response_mode gets invalid_input naming the parameter."""
    data = await call_tool(facade, "get_server_capabilities", {"response_mode": "minimal"})
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"
    assert data["field"] == "response_mode"
