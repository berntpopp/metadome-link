"""Tests for the MCP envelope boundary (success/_meta injection + typed errors)."""

from __future__ import annotations

from typing import Any

import pytest

from metadome_link.constants import DATA_VERSIONS
from metadome_link.exceptions import (
    AmbiguousQueryError,
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
)
from metadome_link.mcp import metrics
from metadome_link.mcp.envelope import (
    McpErrorContext,
    McpToolError,
    classify_exception,
    run_mcp_tool,
)


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    metrics.reset()


async def test_success_injects_success_and_meta() -> None:
    async def call() -> dict[str, Any]:
        return {"transcript_id": "ENST00000269305.4"}

    out = await run_mcp_tool("resolve_transcript", call)
    assert out["success"] is True
    assert out["transcript_id"] == "ENST00000269305.4"
    meta = out["_meta"]
    assert meta["tool"] == "resolve_transcript"
    assert "request_id" in meta
    assert meta["data_versions"] == DATA_VERSIONS


async def test_success_data_versions_always_present_even_minimal() -> None:
    async def call() -> dict[str, Any]:
        return {"ok": 1}

    out = await run_mcp_tool(
        "resolve_transcript",
        call,
        context=McpErrorContext("resolve_transcript", response_mode="minimal"),
    )
    # minimal strips next_commands but data_versions is the universal invariant.
    assert out["_meta"]["data_versions"] == DATA_VERSIONS
    assert "next_commands" not in out["_meta"]


async def test_not_found_error_envelope() -> None:
    async def call() -> dict[str, Any]:
        raise NotFoundError("no such transcript", recovery_action="switch_tool")

    out = await run_mcp_tool(
        "get_tolerance_landscape",
        call,
        context=McpErrorContext("get_tolerance_landscape"),
    )
    assert out["success"] is False
    assert out["error_code"] == "not_found"
    assert out["retryable"] is False
    assert out["recovery_action"] == "switch_tool"
    assert out["_meta"]["data_versions"] == DATA_VERSIONS


async def test_error_default_recovery_action_when_unset() -> None:
    async def call() -> dict[str, Any]:
        raise NotFoundError("nope")

    out = await run_mcp_tool("get_position_tolerance", call)
    assert out["error_code"] == "not_found"
    # falls back to the per-code default
    assert out["recovery_action"] == "reformulate_input"


async def test_invalid_input_propagates_extra_fields() -> None:
    async def call() -> dict[str, Any]:
        raise InvalidInputError(
            "bad id",
            field="transcript_id",
            hint="use ENST...N",
        )

    out = await run_mcp_tool("resolve_transcript", call)
    assert out["error_code"] == "invalid_input"
    assert out["field"] == "transcript_id"
    assert out["hint"] == "use ENST...N"


async def test_invalid_input_allowed_values_propagates() -> None:
    async def call() -> dict[str, Any]:
        raise InvalidInputError(
            "bad mode",
            field="source",
            allowed_values=["both", "gnomad", "clinvar"],
        )

    out = await run_mcp_tool("get_variant_counts", call)
    assert out["allowed_values"] == ["both", "gnomad", "clinvar"]


async def test_retryable_error_marks_retryable() -> None:
    async def call() -> dict[str, Any]:
        raise RateLimitedError("slow down", retryable=True)

    out = await run_mcp_tool("get_tolerance_landscape", call)
    assert out["error_code"] == "rate_limited"
    assert out["retryable"] is True
    assert out["recovery_action"] == "retry_backoff"


async def test_ambiguous_query_surfaces_candidates() -> None:
    candidates = [{"transcript_id": "ENST00000269305.4"}]

    async def call() -> dict[str, Any]:
        raise AmbiguousQueryError("which one?", candidates=candidates)

    out = await run_mcp_tool("resolve_transcript", call)
    assert out["error_code"] == "ambiguous_query"
    assert out["candidates"] == candidates


async def test_mcp_tool_error_uses_explicit_code() -> None:
    async def call() -> dict[str, Any]:
        raise McpToolError("data_unavailable", "cache missing")

    out = await run_mcp_tool("get_diagnostics", call)
    assert out["error_code"] == "data_unavailable"
    assert out["message"] == "cache missing"


async def test_minimal_strips_next_commands_compact_keeps_it() -> None:
    # Tool bodies seed _meta.next_commands themselves (via after_* builders);
    # the envelope keeps it for compact+ and strips it for minimal.
    async def call() -> dict[str, Any]:
        return {
            "ok": True,
            "_meta": {"next_commands": [{"tool": "get_tolerance_landscape", "arguments": {}}]},
        }

    compact = await run_mcp_tool(
        "resolve_transcript",
        call,
        context=McpErrorContext("resolve_transcript", response_mode="compact"),
    )
    assert "next_commands" in compact["_meta"]

    minimal = await run_mcp_tool(
        "resolve_transcript",
        call,
        context=McpErrorContext("resolve_transcript", response_mode="minimal"),
    )
    assert "next_commands" not in minimal["_meta"]


async def test_error_envelope_carries_next_commands_for_compact() -> None:
    # The error path DOES synthesize next_commands (default recovery chain).
    async def call() -> dict[str, Any]:
        raise NotFoundError("nope")

    out = await run_mcp_tool(
        "get_tolerance_landscape",
        call,
        context=McpErrorContext(
            "get_tolerance_landscape",
            arguments={"transcript_id": "ENST00000269305.4"},
        ),
    )
    assert "next_commands" in out["_meta"]
    tools = [step["tool"] for step in out["_meta"]["next_commands"]]
    assert "request_tolerance_landscape" in tools


async def test_standard_includes_elapsed_ms() -> None:
    async def call() -> dict[str, Any]:
        return {"ok": True}

    out = await run_mcp_tool(
        "resolve_transcript",
        call,
        context=McpErrorContext("resolve_transcript", response_mode="standard"),
    )
    assert "elapsed_ms" in out["_meta"]


async def test_classify_exception_taxonomy() -> None:
    assert classify_exception(NotFoundError("x"))[0] == "not_found"
    assert classify_exception(InvalidInputError("x"))[0] == "invalid_input"
    assert classify_exception(RateLimitedError("x"))[0] == "rate_limited"
    assert classify_exception(McpToolError("internal_error", "x"))[0] == "internal_error"
    assert classify_exception(ValueError("boom"))[0] == "internal_error"


async def test_metrics_record_on_success_and_error() -> None:
    async def ok_call() -> dict[str, Any]:
        return {"ok": True}

    async def bad_call() -> dict[str, Any]:
        raise NotFoundError("nope")

    await run_mcp_tool("resolve_transcript", ok_call)
    await run_mcp_tool("resolve_transcript", bad_call)
    snap = metrics.snapshot()
    assert snap["requests"] == 2
    assert snap["errors"] == 1
