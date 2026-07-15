"""Regression guard for the Tool-Surface Budget Standard v1.

The wire tool definitions sit in the model's prompt prefix and are re-sent on every
request. This asserts metadome-link's own advertised surface stays under budget:

* no tool advertises an ``outputSchema`` (the optional field the model never reads
  and the single biggest contributor to the fleet's surface -- suppressed via
  ``@mcp.tool(output_schema=None)``), and
* each tool definition stays under the per-tool ceiling and the whole surface under
  the per-server ceiling.

Token budgets are B1 = 1,200 tokens/tool and B2 = 10,000 tokens/server; measured here
with a conservative ~4 chars/token proxy (the authoritative tokenised gate is the
router's ``make lint-surface`` against the pinned baseline). The proxy is deliberately
generous -- its job is to catch a large regression such as re-advertising every
``outputSchema``, which roughly doubles the surface.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Client

_CHARS_PER_TOKEN = 4
_B1_TOOL_CHARS = 1_200 * _CHARS_PER_TOKEN
_B2_SERVER_CHARS = 10_000 * _CHARS_PER_TOKEN


async def test_no_tool_advertises_output_schema(facade: Any) -> None:
    async with Client(facade) as client:
        tools = await client.list_tools()
    assert tools, "expected the facade to advertise tools"
    offenders = [t.name for t in tools if t.outputSchema is not None]
    assert not offenders, f"tools still advertise outputSchema: {offenders}"


async def test_tool_surface_within_budget(facade: Any) -> None:
    async with Client(facade) as client:
        tools = await client.list_tools()
    total = 0
    for tool in tools:
        blob = tool.model_dump_json(exclude_none=True)
        size = len(blob)
        total += size
        assert size <= _B1_TOOL_CHARS, (
            f"{tool.name} definition is {size} chars (> B1 {_B1_TOOL_CHARS})"
        )
    assert total <= _B2_SERVER_CHARS, (
        f"total tool surface is {total} chars (> B2 {_B2_SERVER_CHARS})"
    )
