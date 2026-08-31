"""End-to-end tests for the server entry points (Task 14).

Three layers are exercised:

1. **FastAPI health** — drive ``metadome_link.app.app`` through an in-process
   ``httpx.ASGITransport`` and assert ``GET /health`` returns 200 with the pinned
   ``data_versions`` and the discovery ``capabilities_version``.
2. **MCP tool surface** — list tools over an in-memory ``fastmcp.Client`` against
   ``create_metadome_mcp(service_factory=...)`` and assert the registered set is
   EXACTLY the frozen 11-tool ``EXPECTED_TOOLS``.
3. **Happy path** — a ``resolve_transcript`` → ``request_tolerance_landscape`` →
   ``get_tolerance_landscape`` walk over the respx-mocked upstream, ending in a
   ``processing`` or ``ready`` landscape (both first-class success states).

The MCP fixtures (``facade``, ``call_tool``, ``mocked_metadome``,
``metadome_service``) come from ``tests/conftest.py``.
"""

from __future__ import annotations

from typing import Any

import httpx

#: The frozen MCP tool surface this server MUST expose — no more, no fewer.
EXPECTED_TOOLS: frozenset[str] = frozenset(
    {
        "get_server_capabilities",
        "get_diagnostics",
        "resolve_transcript",
        "request_tolerance_landscape",
        "get_tolerance_landscape",
        "get_position_tolerance",
        "get_variant_counts",
        "compare_positions",
        "get_protein_domains",
        "get_meta_domain",
        "summarize_intolerant_regions",
    }
)


async def test_health_endpoint_reports_versions() -> None:
    """GET /health returns 200 with status, version, transport + data/capabilities versions."""
    from metadome_link.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str) and body["version"]
    assert body["transport"] == "streamable-http-stateless"
    assert body["data_versions"]["assembly"] == "GRCh38.p14"
    assert isinstance(body["capabilities_version"], str)
    assert body["capabilities_version"]


async def test_facade_lists_exactly_the_eleven_tools(facade: Any) -> None:
    """The in-memory FastMCP facade exposes EXACTLY the 11 frozen tools."""
    from fastmcp import Client

    async with Client(facade) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS, f"unexpected tool set: {names ^ EXPECTED_TOOLS}"


async def test_resolve_request_get_happy_path(facade: Any, call_tool: Any) -> None:
    """resolve_transcript → request_tolerance_landscape → get_tolerance_landscape."""
    resolved = await call_tool(facade, "resolve_transcript", {"query": "TP53"})
    assert resolved["success"] is True

    requested = await call_tool(
        facade, "request_tolerance_landscape", {"transcript_id": "ENST00000269305.9"}
    )
    assert requested["success"] is True
    assert requested["status"] in {"ready", "processing"}

    landscape = await call_tool(
        facade, "get_tolerance_landscape", {"transcript_id": "ENST00000269305.9"}
    )
    assert landscape["success"] is True
    # A ready landscape carries positional_annotation; a still-building job is a
    # first-class status='processing' success state. Accept either.
    if landscape.get("status") == "processing":
        assert landscape["transcript_id"] == "ENST00000269305.9"
    else:
        assert isinstance(landscape["positional_annotation"], list)
