"""Output-schema invariant tests for all 11 MetaDome-Link MCP tools (Task 15).

For every tool, call it in ALL 4 response modes (minimal/compact/standard/full)
on BOTH a success path and a forced-error path, and assert:
  1. The result is a dict with a boolean ``success`` key — no exception raised.
  2. If ``jsonschema`` is importable, explicitly validate the output against the
     tool's ``*_SCHEMA`` constant from ``metadome_link.mcp.schemas``.

The FastMCP in-memory client already validates structured output against the
tool's ``output_schema`` on each call; a returned dict is therefore itself the
primary schema signal. The explicit ``jsonschema.validate`` call is an
additional belt-and-suspenders check that catches regressions in the schema
constants themselves.

Fixtures consumed from ``tests/conftest.py``:
  ``facade``        — FastMCP instance wired to the respx-mocked service.
  ``call_tool``     — in-memory Client helper; returns the raw envelope dict.
  ``mocked_metadome`` — live respx router for per-test route overrides.

NOTE: ``get_diagnostics`` has no forced-error path because it is a pure
local introspection tool that cannot fail under normal circumstances. For the
"error" row we still exercise it in all 4 modes and assert ``success is True``.
"""

from __future__ import annotations

from typing import Any

import pytest

# ── Optional jsonschema ────────────────────────────────────────────────────
try:
    import jsonschema as _jsonschema  # type: ignore[import-untyped]

    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

# ── Schema constants ───────────────────────────────────────────────────────
from metadome_link.mcp import schemas as _s

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_server_capabilities": _s.GET_SERVER_CAPABILITIES_SCHEMA,
    "get_diagnostics": _s.GET_DIAGNOSTICS_SCHEMA,
    "resolve_transcript": _s.RESOLVE_TRANSCRIPT_SCHEMA,
    "request_tolerance_landscape": _s.REQUEST_TOLERANCE_LANDSCAPE_SCHEMA,
    "get_tolerance_landscape": _s.GET_TOLERANCE_LANDSCAPE_SCHEMA,
    "get_position_tolerance": _s.GET_POSITION_TOLERANCE_SCHEMA,
    "get_variant_counts": _s.GET_VARIANT_COUNTS_SCHEMA,
    "compare_positions": _s.COMPARE_POSITIONS_SCHEMA,
    "get_protein_domains": _s.GET_PROTEIN_DOMAINS_SCHEMA,
    "get_meta_domain": _s.GET_META_DOMAIN_SCHEMA,
    "summarize_intolerant_regions": _s.SUMMARIZE_INTOLERANT_REGIONS_SCHEMA,
}

# ── Constants shared across tests ──────────────────────────────────────────
_TID = "ENST00000269305.9"
_BAD_TID = "ENST00000269305"  # missing .N version suffix → invalid_input
_BASE = "https://www.metadome.app/metadome/api"
_RESPONSE_MODES = ["minimal", "compact", "standard", "full"]

# ── Success-path args per tool ─────────────────────────────────────────────
# These args produce a successful response using the default mocked_metadome
# fixture (SUCCESS status, TP53 fixtures). The response_mode is injected by
# the parametrize loop.
_SUCCESS_ARGS: dict[str, dict[str, Any]] = {
    "get_server_capabilities": {},
    "get_diagnostics": {},
    "resolve_transcript": {"query": "TP53"},
    "request_tolerance_landscape": {"transcript_id": _TID},
    "get_tolerance_landscape": {"transcript_id": _TID},
    "get_position_tolerance": {"transcript_id": _TID, "position": 175},
    "get_variant_counts": {"transcript_id": _TID, "position": 35},
    "compare_positions": {"transcript_id": _TID, "positions": [35, 175]},
    "get_protein_domains": {"transcript_id": _TID},
    "get_meta_domain": {"transcript_id": _TID, "position": 175},
    "summarize_intolerant_regions": {"transcript_id": _TID},
}

# ── Forced-error args per tool ─────────────────────────────────────────────
# Each produces a recognised error envelope (success=False, valid error_code).
# Tools that have no meaningful remote-error path use the bad_tid trick.
_ERROR_ARGS: dict[str, dict[str, Any]] = {
    "get_server_capabilities": {},  # no error path; re-use success (see special handling)
    "get_diagnostics": {},  # no error path; re-use success
    "resolve_transcript": {"query": _BAD_TID},  # invalid_input (unversioned ENST)
    "request_tolerance_landscape": {"transcript_id": _BAD_TID},  # invalid_input
    "get_tolerance_landscape": {"transcript_id": _BAD_TID},  # invalid_input
    "get_position_tolerance": {"transcript_id": _TID, "position": 9999},  # invalid_input (OOB)
    "get_variant_counts": {"transcript_id": _TID, "position": 35, "source": "bogus"},  # invalid
    "compare_positions": {"transcript_id": _BAD_TID, "positions": [35, 175]},  # invalid_input
    "get_protein_domains": {"transcript_id": _BAD_TID},  # invalid_input
    "get_meta_domain": {"transcript_id": _BAD_TID, "position": 1},  # invalid_input
    "summarize_intolerant_regions": {"transcript_id": _BAD_TID},  # invalid_input
}

# ── Tools whose "error" scenario is just the success path repeated ──────────
# (no external-error mechanism available without complicated route overriding)
_NO_FORCED_ERROR = frozenset({"get_server_capabilities", "get_diagnostics"})


def _assert_valid(tool: str, output: Any) -> None:
    """Assert ``output`` is a dict with a boolean ``success`` key; optionally schema-validate."""
    assert isinstance(output, dict), f"{tool}: expected dict, got {type(output).__name__}"
    assert isinstance(output.get("success"), bool), (
        f"{tool}: 'success' key missing or not bool; got {output.get('success')!r}"
    )
    if _HAS_JSONSCHEMA:
        schema = _TOOL_SCHEMAS[tool]
        _jsonschema.validate(output, schema)


# ═══════════════════════════════════════════════════════════════════════════
# Success-path parametrize tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("tool_name", list(_TOOL_SCHEMAS.keys()))
@pytest.mark.parametrize("mode", _RESPONSE_MODES)
async def test_output_schema_success_path(
    tool_name: str,
    mode: str,
    facade: Any,
    call_tool: Any,
) -> None:
    """Every tool in every response_mode produces a schema-valid dict on the success path."""
    args = dict(_SUCCESS_ARGS[tool_name])
    args["response_mode"] = mode
    output = await call_tool(facade, tool_name, args)
    _assert_valid(tool_name, output)
    # Success path must return success=True
    assert output["success"] is True, (
        f"{tool_name} mode={mode}: expected success=True, got error_code={output.get('error_code')}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Forced-error path parametrize tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("tool_name", list(_TOOL_SCHEMAS.keys()))
@pytest.mark.parametrize("mode", _RESPONSE_MODES)
async def test_output_schema_error_path(
    tool_name: str,
    mode: str,
    facade: Any,
    call_tool: Any,
) -> None:
    """Every tool in every response_mode produces a schema-valid dict on an error/forced path."""
    args = dict(_ERROR_ARGS[tool_name])
    args["response_mode"] = mode
    output = await call_tool(facade, tool_name, args)
    _assert_valid(tool_name, output)
    # For tools with no forced error, both paths produce success=True — that's fine
    if tool_name not in _NO_FORCED_ERROR:
        assert output["success"] is False, (
            f"{tool_name} mode={mode}: expected forced error (success=False), "
            f"got output keys={list(output.keys())}"
        )
