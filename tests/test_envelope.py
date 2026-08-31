"""Tests for the MCP envelope boundary (success/_meta injection + typed errors)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastmcp.tools.tool import ToolResult

from metadome_link.constants import DATA_VERSIONS, MAX_RESPONSE_CHARS
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


async def _run(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Await a tool and return its envelope dict.

    On error :func:`run_mcp_tool` returns a ``ToolResult`` flagged ``is_error=True``
    (Response-Envelope Standard v1); unwrap its ``structured_content`` so these
    envelope-content assertions read the same dict on both paths.
    """
    res = await run_mcp_tool(*args, **kwargs)
    if isinstance(res, ToolResult):
        assert res.is_error is True
        assert isinstance(res.structured_content, dict)
        return res.structured_content
    return res


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    metrics.reset()


async def test_success_injects_success_and_meta() -> None:
    async def call() -> dict[str, Any]:
        return {"transcript_id": "ENST00000269305.9"}

    out = await _run("resolve_transcript", call)
    assert out["success"] is True
    assert out["transcript_id"] == "ENST00000269305.9"
    meta = out["_meta"]
    assert meta["tool"] == "resolve_transcript"
    assert "request_id" in meta
    assert meta["data_versions"] == DATA_VERSIONS


async def test_success_data_versions_always_present_even_minimal() -> None:
    async def call() -> dict[str, Any]:
        return {"ok": 1}

    out = await _run(
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

    out = await _run(
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

    out = await _run("get_position_tolerance", call)
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

    out = await _run("resolve_transcript", call)
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

    out = await _run("get_variant_counts", call)
    assert out["allowed_values"] == ["both", "gnomad", "clinvar"]


async def test_retryable_error_marks_retryable() -> None:
    async def call() -> dict[str, Any]:
        raise RateLimitedError("slow down", retryable=True)

    out = await _run("get_tolerance_landscape", call)
    assert out["error_code"] == "rate_limited"
    assert out["retryable"] is True
    assert out["recovery_action"] == "retry_backoff"


async def test_ambiguous_query_surfaces_candidates() -> None:
    candidates = [{"transcript_id": "ENST00000269305.9"}]

    async def call() -> dict[str, Any]:
        raise AmbiguousQueryError("which one?", candidates=candidates)

    out = await _run("resolve_transcript", call)
    assert out["error_code"] == "ambiguous_query"
    assert out["candidates"] == candidates


async def test_mcp_tool_error_uses_explicit_code() -> None:
    async def call() -> dict[str, Any]:
        raise McpToolError("data_unavailable", "cache missing")  # off-enum -> canonicalized

    out = await _run("get_diagnostics", call)
    assert out["error_code"] == "upstream_unavailable"
    assert out["message"] == "cache missing"


async def test_error_path_sets_mcp_is_error_success_path_does_not() -> None:
    """Response-Envelope v1: an error envelope MUST ride an ``is_error=True`` ToolResult.

    A plain error dict is ``isError=false`` on the wire -- a client branching on MCP
    ``isError`` would read the failure as a successful call. The success path stays a
    plain dict (FastMCP injects it as ``structuredContent``).
    """

    async def failing() -> dict[str, Any]:
        raise NotFoundError("no landscape")

    err = await run_mcp_tool("get_tolerance_landscape", failing)
    assert isinstance(err, ToolResult)
    assert err.is_error is True
    assert isinstance(err.structured_content, dict)
    assert err.structured_content["success"] is False
    assert err.structured_content["error_code"] == "not_found"

    async def ok() -> dict[str, Any]:
        return {"transcript_id": "ENST00000269305.9"}

    good = await run_mcp_tool("resolve_transcript", ok)
    assert not isinstance(good, ToolResult)
    assert good["success"] is True


async def test_minimal_strips_next_commands_compact_keeps_it() -> None:
    # Tool bodies seed _meta.next_commands themselves (via after_* builders);
    # the envelope keeps it for compact+ and strips it for minimal.
    async def call() -> dict[str, Any]:
        return {
            "ok": True,
            "_meta": {"next_commands": [{"tool": "get_tolerance_landscape", "arguments": {}}]},
        }

    compact = await _run(
        "resolve_transcript",
        call,
        context=McpErrorContext("resolve_transcript", response_mode="compact"),
    )
    assert "next_commands" in compact["_meta"]

    minimal = await _run(
        "resolve_transcript",
        call,
        context=McpErrorContext("resolve_transcript", response_mode="minimal"),
    )
    assert "next_commands" not in minimal["_meta"]


async def test_error_envelope_carries_next_commands_for_compact() -> None:
    # The error path DOES synthesize next_commands (default recovery chain).
    async def call() -> dict[str, Any]:
        raise NotFoundError("nope")

    out = await _run(
        "get_tolerance_landscape",
        call,
        context=McpErrorContext(
            "get_tolerance_landscape",
            arguments={"transcript_id": "ENST00000269305.9"},
        ),
    )
    assert "next_commands" in out["_meta"]
    tools = [step["tool"] for step in out["_meta"]["next_commands"]]
    assert "request_tolerance_landscape" in tools


async def test_standard_includes_elapsed_ms() -> None:
    async def call() -> dict[str, Any]:
        return {"ok": True}

    out = await _run(
        "resolve_transcript",
        call,
        context=McpErrorContext("resolve_transcript", response_mode="standard"),
    )
    assert "elapsed_ms" in out["_meta"]


async def test_classify_exception_taxonomy() -> None:
    assert classify_exception(NotFoundError("x"))[0] == "not_found"
    assert classify_exception(InvalidInputError("x"))[0] == "invalid_input"
    assert classify_exception(RateLimitedError("x"))[0] == "rate_limited"
    assert classify_exception(McpToolError("internal_error", "x"))[0] == "internal"
    assert classify_exception(ValueError("boom"))[0] == "internal"


async def test_metrics_record_on_success_and_error() -> None:
    async def ok_call() -> dict[str, Any]:
        return {"ok": True}

    async def bad_call() -> dict[str, Any]:
        raise NotFoundError("nope")

    await _run("resolve_transcript", ok_call)
    await _run("resolve_transcript", bad_call)
    snap = metrics.snapshot()
    assert snap["requests"] == 2
    assert snap["errors"] == 1


async def test_oversized_success_payload_is_budget_guarded() -> None:
    """A success payload over the hard cap comes back truncated with a
    ``dropped_summary``, at/under the budget, while ``_meta`` survives intact."""

    async def call() -> dict[str, Any]:
        # ~1500 fat rows -> well over MAX_RESPONSE_CHARS as a top-level list,
        # plus a nested meta-domain list to exercise the nested-truncation path.
        return {
            "transcript_id": "ENST00000269305.9",
            "gene_name": "TP53",
            "positional_annotation": [
                {"protein_pos": i, "ref_aa": "A", "sw_dn_ds": 0.123456789, "pad": "x" * 40}
                for i in range(1500)
            ],
            "meta_domains": {
                "PF00870": {
                    "pathogenic_variants": [
                        {"clinvar_ID": str(i), "pad": "y" * 40} for i in range(800)
                    ],
                },
            },
        }

    out = await _run(
        "get_tolerance_landscape",
        call,
        context=McpErrorContext("get_tolerance_landscape", response_mode="full"),
    )

    # The guard fired and recorded what it dropped.
    assert "dropped_summary" in out
    # Serialised size is at/under the budget.
    assert len(json.dumps(out)) <= MAX_RESPONSE_CHARS
    # The big lists were reduced from their originals.
    assert len(out["positional_annotation"]) < 1500
    # _meta survives intact and is NOT truncated/dropped.
    meta = out["_meta"]
    assert meta["tool"] == "get_tolerance_landscape"
    assert out["success"] is True
    assert meta["data_versions"] == DATA_VERSIONS


async def test_normal_payload_unaffected_by_budget_guard() -> None:
    """A small payload passes through the guard untouched (no dropped_summary)."""

    async def call() -> dict[str, Any]:
        return {"transcript_id": "ENST00000269305.9", "positions": [1, 2, 3]}

    out = await _run("get_position_tolerance", call)
    assert "dropped_summary" not in out
    assert out["positions"] == [1, 2, 3]
