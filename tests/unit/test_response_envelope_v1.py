"""Locking regression test for the GeneFoundry Response-Envelope Standard v1.

This repo (``metadome-link``) implements the ratified envelope contract at its
MCP wrapper boundary (``metadome_link/mcp/envelope.py::run_mcp_tool``), which is
the SINGLE mechanism that builds BOTH the success envelope's ``_meta`` and the
flat error envelope (there is no separate ``mcp/errors.py`` in this repo -- both
paths live in ``envelope.py``).

Per the standard:
  - SUCCESS: ``{"success": True, <payload>, "_meta": {...}}``.
  - FAILURE: a FLAT in-band dict -- ``{"success": False, "error_code": <str>,
    "message": <str>, "retryable": <bool>, "recovery_action": <str>,
    "_meta": {...}}`` -- NEVER a bare exception, NEVER a nested ``error: {}``
    shape.

This test exercises the contract at TWO levels:
  1. Directly against ``run_mcp_tool`` (the envelope-boundary unit), matching
     the existing coverage style in ``tests/test_envelope.py``.
  2. End-to-end through a REAL registered MCP tool (``resolve_transcript``) via
     the in-memory FastMCP client (the ``facade``/``call_tool`` fixtures from
     ``tests/conftest.py``), so the lock also covers tool-registration wiring,
     not just the envelope helper in isolation.

Ground-truth note (drift from the ideal fleet contract, intentionally NOT
papered over): metadome-link's ``_meta`` does NOT carry an
``unsafe_for_clinical_use`` flag on ANY response, success or error. The
research-use disclaimer (``research_use_only: True`` + a notice string) is
surfaced only in ``get_server_capabilities`` / discovery resources, not
per-call. This test asserts what the repo actually ships (``tool``,
``request_id``, ``data_versions`` on every ``_meta``) rather than asserting
a key that does not exist.
"""

from __future__ import annotations

from typing import Any

from metadome_link.constants import DATA_VERSIONS
from metadome_link.exceptions import NotFoundError
from metadome_link.mcp.envelope import McpErrorContext, run_mcp_tool

_BAD_TID = "ENST00000269305"  # missing the required `.N` version suffix


# ═══════════════════════════════════════════════════════════════════════════
# Level 1: direct envelope-boundary unit tests (run_mcp_tool)
# ═══════════════════════════════════════════════════════════════════════════


async def test_v1_success_envelope_is_flat_banner_with_real_meta_keys() -> None:
    """SUCCESS envelope: {"success": True, <payload>, "_meta": {...}} -- flat, no wrapping."""

    async def call() -> dict[str, Any]:
        return {"transcript_id": "ENST00000269305.4", "gene_name": "TP53"}

    out = await run_mcp_tool("resolve_transcript", call)

    assert out["success"] is True
    # Payload keys live at the top level, not nested under a "result"/"data" wrapper.
    assert out["transcript_id"] == "ENST00000269305.4"
    assert out["gene_name"] == "TP53"

    meta = out["_meta"]
    # Real, actually-shipped _meta invariants (see module docstring for the
    # unsafe_for_clinical_use drift note -- that key does not exist here).
    assert meta["tool"] == "resolve_transcript"
    assert isinstance(meta["request_id"], str) and meta["request_id"]
    assert meta["data_versions"] == DATA_VERSIONS
    assert "unsafe_for_clinical_use" not in meta


async def test_v1_error_envelope_is_flat_never_nested() -> None:
    """FAILURE envelope: flat success=False dict, never a bare exception or nested error{}."""

    async def call() -> dict[str, Any]:
        raise NotFoundError("no such transcript")

    out = await run_mcp_tool(
        "get_tolerance_landscape",
        call,
        context=McpErrorContext("get_tolerance_landscape"),
    )

    assert out["success"] is False
    assert isinstance(out["error_code"], str) and out["error_code"]
    assert out["error_code"] == "not_found"
    assert isinstance(out["message"], str) and out["message"]
    assert isinstance(out["retryable"], bool)
    assert out.get("recovery_action")
    # The flat-banner invariant: no nested "error" object anywhere in the envelope.
    assert "error" not in out

    meta = out["_meta"]
    assert meta["tool"] == "get_tolerance_landscape"
    assert isinstance(meta["request_id"], str) and meta["request_id"]
    assert meta["data_versions"] == DATA_VERSIONS
    assert "unsafe_for_clinical_use" not in meta


# ═══════════════════════════════════════════════════════════════════════════
# Level 2: end-to-end through a REAL registered tool (resolve_transcript)
# ═══════════════════════════════════════════════════════════════════════════


async def test_v1_real_tool_success_conforms_to_flat_banner(
    facade: Any,
    call_tool: Any,
) -> None:
    """A real, registered MCP tool call produces the flat success banner."""
    out = await call_tool(facade, "resolve_transcript", {"query": "TP53"})

    assert out["success"] is True
    assert "error" not in out
    meta = out["_meta"]
    assert meta["tool"] == "resolve_transcript"
    assert "request_id" in meta
    assert meta["data_versions"] == DATA_VERSIONS


async def test_v1_real_tool_error_conforms_to_flat_banner(
    facade: Any,
    call_tool: Any,
) -> None:
    """A real, registered MCP tool call driven into a genuine invalid_input path
    produces the flat FAILURE banner -- success=False, no nested error{}."""
    out = await call_tool(facade, "resolve_transcript", {"query": _BAD_TID})

    assert out["success"] is False
    assert isinstance(out["error_code"], str) and out["error_code"]
    assert isinstance(out["message"], str) and out["message"]
    assert isinstance(out["retryable"], bool)
    assert out.get("recovery_action")
    assert "error" not in out

    meta = out["_meta"]
    assert meta["tool"] == "resolve_transcript"
    assert "unsafe_for_clinical_use" not in meta
