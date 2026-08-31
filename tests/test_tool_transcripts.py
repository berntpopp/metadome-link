"""Tests for the ``resolve_transcript`` MCP tool (Task 9).

All tests use the shared ``facade`` + ``call_tool`` + ``mocked_metadome``
fixtures from ``conftest.py``:

- ``facade``         — a real ``FastMCP`` with the respx-mocked service injected.
- ``call_tool``      — an in-memory ``fastmcp.Client`` helper; returns the raw
  ``{success, _meta, ...}`` dict (including error envelopes).
- ``mocked_metadome``— the live respx router so individual tests can override
  routes before calling the tool.

The canonical transcript for TP53 in the fixture is ENST00000269305.9
(aa_length=393, has_protein_data=true, MANE Select).
"""

from __future__ import annotations

import httpx
import respx

from tests.conftest import TID

# ---------------------------------------------------------------------------
# Gene → transcript list (happy path)
# ---------------------------------------------------------------------------


async def test_resolve_tp53_returns_success(facade: object, call_tool: object) -> None:
    """resolve_transcript("TP53") succeeds with the full transcript list."""
    data = await call_tool(facade, "resolve_transcript", {"query": "TP53"})  # type: ignore[operator]
    assert data["success"] is True


async def test_resolve_tp53_canonical_flagged(facade: object, call_tool: object) -> None:
    """The analyzable MANE Select transcript is flagged canonical."""
    data = await call_tool(facade, "resolve_transcript", {"query": "TP53"})  # type: ignore[operator]
    assert data.get("canonical_transcript_id") == TID
    transcripts = data.get("transcripts", [])
    assert any(t for t in transcripts if t.get("canonical") is True and t.get("gencode_id") == TID)


async def test_resolve_tp53_next_commands_includes_request_landscape(
    facade: object, call_tool: object
) -> None:
    """_meta.next_commands includes request_tolerance_landscape for the canonical transcript."""
    data = await call_tool(facade, "resolve_transcript", {"query": "TP53"})  # type: ignore[operator]
    next_cmds = data.get("_meta", {}).get("next_commands", [])
    tool_names = [nc.get("tool") for nc in next_cmds]
    assert "request_tolerance_landscape" in tool_names


async def test_resolve_tp53_next_commands_canonical_id(facade: object, call_tool: object) -> None:
    """next_commands.request_tolerance_landscape uses the canonical transcript id."""
    data = await call_tool(facade, "resolve_transcript", {"query": "TP53"})  # type: ignore[operator]
    next_cmds = data.get("_meta", {}).get("next_commands", [])
    req_cmd = next(
        (nc for nc in next_cmds if nc.get("tool") == "request_tolerance_landscape"), None
    )
    assert req_cmd is not None
    assert req_cmd.get("arguments", {}).get("transcript_id") == TID


async def test_resolve_tp53_has_recommended_citation(facade: object, call_tool: object) -> None:
    """The response carries recommended_citation with the Wiel 2019 DOI."""
    data = await call_tool(facade, "resolve_transcript", {"query": "TP53"})  # type: ignore[operator]
    citation = data.get("recommended_citation", "")
    assert "humu.23798" in citation


async def test_resolve_tp53_transcripts_sorted_by_length(facade: object, call_tool: object) -> None:
    """Transcripts are sorted by aa_length descending."""
    data = await call_tool(facade, "resolve_transcript", {"query": "TP53"})  # type: ignore[operator]
    lengths = [t["aa_length"] for t in data.get("transcripts", [])]
    assert lengths == sorted(lengths, reverse=True)


async def test_resolve_tp53_meta_data_versions_present(facade: object, call_tool: object) -> None:
    """_meta always carries data_versions."""
    data = await call_tool(facade, "resolve_transcript", {"query": "TP53"})  # type: ignore[operator]
    assert "data_versions" in data.get("_meta", {})
    assert data["_meta"]["data_versions"].get("assembly") == "GRCh38.p14"


# ---------------------------------------------------------------------------
# ENST id pass-through
# ---------------------------------------------------------------------------


async def test_resolve_enst_passthrough(facade: object, call_tool: object) -> None:
    """A bare ENST id is validated and echoed (resolved_from="id")."""
    data = await call_tool(facade, "resolve_transcript", {"query": TID})  # type: ignore[operator]
    assert data["success"] is True
    assert data.get("transcript_id") == TID
    assert data.get("resolved_from") == "id"


async def test_resolve_enst_passthrough_next_commands(facade: object, call_tool: object) -> None:
    """An ENST id path also steers to request_tolerance_landscape."""
    data = await call_tool(facade, "resolve_transcript", {"query": TID})  # type: ignore[operator]
    next_cmds = data.get("_meta", {}).get("next_commands", [])
    tool_names = [nc.get("tool") for nc in next_cmds]
    assert "request_tolerance_landscape" in tool_names
    req_cmd = next(
        (nc for nc in next_cmds if nc.get("tool") == "request_tolerance_landscape"), None
    )
    assert req_cmd is not None
    assert req_cmd.get("arguments", {}).get("transcript_id") == TID


async def test_resolve_unversioned_enst_returns_invalid_input(
    facade: object, call_tool: object
) -> None:
    """An ENST id without the .N version suffix → invalid_input error."""
    data = await call_tool(facade, "resolve_transcript", {"query": "ENST00000269305"})  # type: ignore[operator]
    assert data["success"] is False
    assert data.get("error_code") == "invalid_input"


# ---------------------------------------------------------------------------
# Unknown gene → not_found
# ---------------------------------------------------------------------------


async def test_resolve_unknown_gene_returns_not_found(
    mocked_metadome: respx.MockRouter, facade: object, call_tool: object
) -> None:
    """An unknown gene symbol → error_code:"not_found"."""
    mocked_metadome.get("/get_transcripts/GRCh38.p14/NOSUCHGENE999").mock(
        return_value=httpx.Response(
            200,
            json={"message": "No transcripts", "genome_build": "GRCh38.p14", "transcript_ids": []},
        )
    )
    data = await call_tool(facade, "resolve_transcript", {"query": "NOSUCHGENE999"})  # type: ignore[operator]
    assert data["success"] is False
    assert data.get("error_code") == "not_found"


# ---------------------------------------------------------------------------
# response_mode
# ---------------------------------------------------------------------------


async def test_resolve_minimal_mode_drops_next_commands(facade: object, call_tool: object) -> None:
    """response_mode=minimal strips next_commands from _meta."""
    data = await call_tool(  # type: ignore[operator]
        facade, "resolve_transcript", {"query": "TP53", "response_mode": "minimal"}
    )
    assert data["success"] is True
    # minimal _meta contains only tool/request_id/data_versions, no next_commands
    assert "next_commands" not in data.get("_meta", {})


async def test_resolve_compact_mode_includes_next_commands(
    facade: object, call_tool: object
) -> None:
    """response_mode=compact (default) keeps next_commands in _meta."""
    data = await call_tool(  # type: ignore[operator]
        facade, "resolve_transcript", {"query": "TP53", "response_mode": "compact"}
    )
    assert data["success"] is True
    assert "next_commands" in data.get("_meta", {})
