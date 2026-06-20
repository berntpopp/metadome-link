"""Tests for ``metadome://`` resources and tool-registry parity (Task 15).

Two things are verified here:

1. **Resource coverage**: each registered ``metadome://`` resource URI
   (capabilities, tools, usage, reference, research-use, citation) returns
   non-empty content via the in-memory FastMCP Client.

2. **Tool parity**: ``build_capabilities()["tools"]`` (the static contract)
   must equal EXACTLY the set of tool names that are actually registered on a
   ``create_metadome_mcp()`` facade, as reported by ``mcp.list_tools()`` and by
   the in-memory Client ``list_tools()``. Both introspection routes must agree,
   and both must match the 11-name frozen list from ``capabilities.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from metadome_link.mcp.capabilities import TOOLS, build_capabilities

# ── Expected frozen tool set ───────────────────────────────────────────────
EXPECTED_TOOLS: frozenset[str] = frozenset(TOOLS)
assert len(EXPECTED_TOOLS) == 11, f"Expected 11 tools, got {len(EXPECTED_TOOLS)}"

# ── Expected resource URIs ────────────────────────────────────────────────
EXPECTED_RESOURCE_URIS: list[str] = [
    "metadome://capabilities",
    "metadome://tools",
    "metadome://usage",
    "metadome://reference",
    "metadome://research-use",
    "metadome://citation",
]


# ═══════════════════════════════════════════════════════════════════════════
# Resource content tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("uri", EXPECTED_RESOURCE_URIS)
async def test_resource_returns_non_empty_content(
    uri: str,
    facade: Any,
) -> None:
    """Each registered metadome:// resource returns a non-empty text payload."""
    async with Client(facade) as client:
        result = await client.read_resource(uri)
    # result is a list of content items (TextResourceContents / BlobResourceContents)
    assert isinstance(result, list) and len(result) >= 1, (
        f"Resource {uri!r}: expected non-empty list, got {result!r}"
    )
    content_item = result[0]
    # TextResourceContents has a .text attribute; BlobResourceContents has .blob
    text = getattr(content_item, "text", None) or getattr(content_item, "blob", None)
    assert text, f"Resource {uri!r}: content is empty or missing"
    if isinstance(text, str):
        assert len(text.strip()) > 0, f"Resource {uri!r}: text content is blank"


async def test_capabilities_resource_is_valid_json(facade: Any) -> None:
    """metadome://capabilities returns valid JSON with the expected keys."""
    import json

    async with Client(facade) as client:
        result = await client.read_resource("metadome://capabilities")
    text = result[0].text
    data = json.loads(text)
    assert data["server"] == "metadome-link"
    assert data["tool_count"] == 11
    assert set(data["tools"]) == EXPECTED_TOOLS


async def test_tools_resource_contains_all_11(facade: Any) -> None:
    """metadome://tools lists exactly the 11 registered tools."""
    import json

    async with Client(facade) as client:
        result = await client.read_resource("metadome://tools")
    data = json.loads(result[0].text)
    assert set(data["tools"]) == EXPECTED_TOOLS
    assert data["tool_count"] == 11


async def test_research_use_resource_contains_disclaimer(facade: Any) -> None:
    """metadome://research-use contains the research-use disclaimer."""
    async with Client(facade) as client:
        result = await client.read_resource("metadome://research-use")
    text = result[0].text
    assert "Research use only" in text


async def test_citation_resource_contains_doi(facade: Any) -> None:
    """metadome://citation contains the Wiel 2019 DOI."""
    async with Client(facade) as client:
        result = await client.read_resource("metadome://citation")
    text = result[0].text
    assert "humu.23798" in text


async def test_usage_resource_contains_workflow_hint(facade: Any) -> None:
    """metadome://usage contains a workflow hint."""
    async with Client(facade) as client:
        result = await client.read_resource("metadome://usage")
    text = result[0].text
    assert "resolve_transcript" in text


async def test_reference_resource_contains_error_codes(facade: Any) -> None:
    """metadome://reference mentions the 7-code error taxonomy."""
    async with Client(facade) as client:
        result = await client.read_resource("metadome://reference")
    text = result[0].text
    assert "invalid_input" in text
    assert "not_found" in text


# ═══════════════════════════════════════════════════════════════════════════
# Tool-registry parity tests
# ═══════════════════════════════════════════════════════════════════════════

async def test_build_capabilities_tools_matches_facade_list_tools(facade: Any) -> None:
    """build_capabilities()['tools'] must match the facade's list_tools() exactly."""
    # Server-side introspection (FastMCP.list_tools — returns FunctionTool objects)
    server_tools = await facade.list_tools()
    server_names = frozenset(t.name for t in server_tools)

    caps_names = frozenset(build_capabilities()["tools"])
    assert caps_names == server_names, (
        f"Parity failure (server vs caps):\n"
        f"  in caps but not server: {caps_names - server_names}\n"
        f"  in server but not caps: {server_names - caps_names}"
    )


async def test_build_capabilities_tools_matches_client_list_tools(facade: Any) -> None:
    """build_capabilities()['tools'] must match what the in-memory Client sees."""
    async with Client(facade) as client:
        client_tools = await client.list_tools()
    client_names = frozenset(t.name for t in client_tools)

    caps_names = frozenset(build_capabilities()["tools"])
    assert caps_names == client_names, (
        f"Parity failure (client vs caps):\n"
        f"  in caps but not client: {caps_names - client_names}\n"
        f"  in client but not caps: {client_names - caps_names}"
    )


async def test_registered_tool_count_is_11(facade: Any) -> None:
    """Exactly 11 tools are registered on the facade."""
    tools = await facade.list_tools()
    assert len(tools) == 11, (
        f"Expected 11 registered tools, got {len(tools)}: {[t.name for t in tools]}"
    )


async def test_all_expected_tools_are_registered(facade: Any) -> None:
    """Each of the 11 expected tool names is present in the facade."""
    tools = await facade.list_tools()
    registered = frozenset(t.name for t in tools)
    missing = EXPECTED_TOOLS - registered
    assert not missing, f"Missing tools: {missing}"


async def test_no_unexpected_tools_registered(facade: Any) -> None:
    """No tool names beyond the expected 11 are registered."""
    tools = await facade.list_tools()
    registered = frozenset(t.name for t in tools)
    extra = registered - EXPECTED_TOOLS
    assert not extra, f"Unexpected tools registered: {extra}"


async def test_capabilities_list_and_facade_agree(facade: Any) -> None:
    """TOOLS constant, build_capabilities()['tools'], and facade.list_tools() all agree."""
    server_tools = await facade.list_tools()
    server_names = frozenset(t.name for t in server_tools)

    constant_names = frozenset(TOOLS)
    caps_names = frozenset(build_capabilities()["tools"])

    assert constant_names == caps_names == server_names, (
        f"Three-way mismatch:\n"
        f"  TOOLS constant:      {sorted(constant_names)}\n"
        f"  build_capabilities: {sorted(caps_names)}\n"
        f"  facade list_tools:   {sorted(server_names)}"
    )
