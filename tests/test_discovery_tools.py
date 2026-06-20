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
    assert meta["data_versions"]["assembly"] == "GRCh37"


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
    assert data["data_versions"]["assembly"] == "GRCh37"
    assert data["_meta"]["capabilities_version"]
