"""Position tool tests through the real FastMCP facade (Task 11).

These exercise the full MCP path: facade -> envelope -> position tool body ->
injected (respx-mocked) service. The default ``mocked_metadome`` router returns a
SUCCESS status and the bundled ``result_TP53.json`` fixture, so the landscape is
"ready" for the first call (the service caches it on poll).

FIXTURE CAVEAT: the trimmed fixture has ~20 non-contiguous residues. Tests use
positions that EXIST in it: 35 (ClinVar), 175 (meta-domain mapping), 248. An
out-of-range position (9999) yields ``invalid_input``.
"""

from __future__ import annotations

from typing import Any

import httpx

TID = "ENST00000269305.9"


async def test_get_position_tolerance_returns_sw_dn_ds(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """get_position_tolerance for p.175 returns its sw_dn_ds + a citation."""
    data = await call_tool(
        facade,
        "get_position_tolerance",
        {"transcript_id": TID, "position": 175, "response_mode": "standard"},
    )
    assert data["success"] is True
    assert data["protein_pos"] == 175
    assert data["ref_aa"] == "R"
    assert data["sw_dn_ds"] == 0.44289044289044294
    assert "recommended_citation" in data
    assert data["_meta"]["next_commands"]


async def test_get_position_tolerance_out_of_range_invalid_input(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """An out-of-range position yields an invalid_input error envelope."""
    data = await call_tool(
        facade,
        "get_position_tolerance",
        {"transcript_id": TID, "position": 9999},
    )
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


async def test_get_position_tolerance_suggests_meta_domain(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """A residue with meta-domain mapping suggests get_meta_domain next."""
    data = await call_tool(
        facade,
        "get_position_tolerance",
        {"transcript_id": TID, "position": 175},
    )
    assert data["success"] is True
    tools = [c["tool"] for c in data["_meta"]["next_commands"]]
    assert "get_meta_domain" in tools


async def test_get_variant_counts_source_both(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """source='both' returns both explicitly-scoped evidence groups for p.35."""
    data = await call_tool(
        facade,
        "get_variant_counts",
        {"transcript_id": TID, "position": 35, "source": "both"},
    )
    assert data["success"] is True
    evidence = data["positions"][0]["variant_evidence"]
    assert "gnomad" in evidence["residue_level"]
    assert "clinvar" in evidence["residue_level"]


async def test_get_variant_counts_source_gnomad_only(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """source='gnomad' excludes the clinvar count group (and clinvar_variants)."""
    data = await call_tool(
        facade,
        "get_variant_counts",
        {"transcript_id": TID, "position": 35, "source": "gnomad"},
    )
    assert data["success"] is True
    row = data["positions"][0]
    evidence = row["variant_evidence"]
    assert "gnomad" in evidence["residue_level"]
    assert "clinvar" not in evidence["residue_level"]
    assert "clinvar_variants" not in row


async def test_get_variant_counts_clinvar_id_present(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """source='clinvar' surfaces the ClinVar variant id + NCBI url for p.35."""
    data = await call_tool(
        facade,
        "get_variant_counts",
        {"transcript_id": TID, "position": 35, "source": "clinvar"},
    )
    assert data["success"] is True
    row = data["positions"][0]
    assert "gnomad" not in row["variant_evidence"]["residue_level"]
    variants = row["clinvar_variants"]
    assert any(v.get("clinvar_ID") == "12371" for v in variants)
    assert all(v["url"].startswith("https://www.ncbi.nlm.nih.gov/clinvar/") for v in variants)


async def test_get_variant_counts_schema_exposes_limit_offset(facade: Any) -> None:
    """The MCP input schema exposes whole-protein pagination controls."""
    tools = await facade.list_tools()
    tool = next(t for t in tools if t.name == "get_variant_counts")
    properties = tool.parameters["properties"]
    assert properties["limit"]["default"] == 200
    assert properties["offset"]["default"] == 0


async def test_get_variant_counts_whole_protein_paginates_with_next_command(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """A low-limit whole-protein request returns a forward-page next_command."""
    data = await call_tool(
        facade,
        "get_variant_counts",
        {"transcript_id": TID, "limit": 2, "offset": 0, "response_mode": "compact"},
    )
    assert data["success"] is True
    assert len(data["positions"]) == 2
    assert data["pagination"]["limit"] == 2
    assert data["pagination"]["offset"] == 0
    assert data["pagination"]["truncated"] is True
    assert data["pagination"]["next_offset"] == 2

    page_commands = [
        command
        for command in data["_meta"]["next_commands"]
        if command["tool"] == "get_variant_counts" and command["arguments"].get("offset") == 2
    ]
    assert page_commands
    assert page_commands[0]["arguments"]["transcript_id"] == TID
    assert page_commands[0]["arguments"]["limit"] == 2


async def test_get_variant_counts_bad_source_invalid_input(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """An unknown source value yields invalid_input."""
    data = await call_tool(
        facade,
        "get_variant_counts",
        {"transcript_id": TID, "position": 35, "source": "bogus"},
    )
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


async def test_compare_positions_table(facade: Any, call_tool: Any, mocked_metadome: Any) -> None:
    """compare_positions returns one row per requested position."""
    data = await call_tool(
        facade,
        "compare_positions",
        {"transcript_id": TID, "positions": [35, 175, 248], "response_mode": "standard"},
    )
    assert data["success"] is True
    rows = {r["protein_pos"]: r for r in data["comparison"]}
    assert set(rows) == {35, 175, 248}
    assert rows[175]["sw_dn_ds"] == 0.44289044289044294
    assert rows[248]["ref_aa"] == "R"


async def test_compare_positions_per_item_error(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """A bad position in the batch yields a per-item error, not a failed call."""
    data = await call_tool(
        facade,
        "compare_positions",
        {"transcript_id": TID, "positions": [175, 9999]},
    )
    assert data["success"] is True
    rows = {r["protein_pos"]: r for r in data["comparison"]}
    assert "error" in rows[9999]
    assert "error" not in rows[175]


async def test_position_tool_not_ready_not_found(
    facade: Any,
    call_tool: Any,
    mocked_metadome: Any,
    metadome_service: Any,
) -> None:
    """A not-yet-built landscape yields not_found + recovery switch_tool."""
    # Collapse the poll deadline so the still-building path returns fast.
    metadome_service._settings.metadome.poll_soft_deadline_s = 0.05
    mocked_metadome.get(f"/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    data = await call_tool(
        facade,
        "get_position_tolerance",
        {"transcript_id": TID, "position": 175},
    )
    assert data["success"] is False
    assert data["error_code"] == "not_found"
    assert data["recovery_action"] == "switch_tool"
