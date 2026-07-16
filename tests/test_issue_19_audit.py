"""Regression coverage for the confirmed MCP audit issue #19 defects."""

from __future__ import annotations

import json
from typing import Any

import pytest

from metadome_link.mcp.envelope import McpErrorContext, run_mcp_tool
from metadome_link.services.shaping import char_budget_guard

TID = "ENST00000269305.4"


async def test_position_and_comparison_expose_provenanced_variant_evidence(
    facade: Any, call_tool: Any
) -> None:
    """Homolog aggregates must never masquerade as this residue's variant counts."""
    position = await call_tool(
        facade,
        "get_position_tolerance",
        {"transcript_id": TID, "position": 175, "response_mode": "standard"},
    )
    comparison = await call_tool(
        facade,
        "compare_positions",
        {"transcript_id": TID, "positions": [175], "response_mode": "standard"},
    )

    for row in (position, comparison["comparison"][0]):
        assert "counts" not in row
        evidence = row["variant_evidence"]
        assert evidence["residue_level"]["gnomad"]["available"] is False
        assert evidence["residue_level"]["clinvar"]["variant_count"] == 1
        homologs = evidence["meta_domain_homolog_aggregate"]
        assert homologs["gnomad"]["variant_count"] == 2
        assert homologs["clinvar"]["variant_count"] == 2
        assert "other genes" in homologs["provenance"]


async def test_variant_counts_separate_actual_clinvar_from_homolog_aggregates(
    facade: Any, call_tool: Any
) -> None:
    """ClinVar's headline count must match its listed variants, unlike the homolog aggregate."""
    data = await call_tool(
        facade,
        "get_variant_counts",
        {"transcript_id": TID, "position": 175, "source": "both", "response_mode": "standard"},
    )

    row = data["positions"][0]
    assert "counts" not in row
    evidence = row["variant_evidence"]
    assert evidence["residue_level"]["gnomad"]["available"] is False
    assert evidence["residue_level"]["clinvar"]["variant_count"] == len(row["clinvar_variants"])
    assert evidence["meta_domain_homolog_aggregate"]["clinvar"]["variant_count"] == 2
    assert "other genes" in evidence["meta_domain_homolog_aggregate"]["provenance"]


async def test_non_metadomain_residue_never_reports_a_gnomad_zero(
    facade: Any, call_tool: Any
) -> None:
    """A residue outside Pfam is unavailable, not population evidence with count zero."""
    data = await call_tool(
        facade,
        "get_variant_counts",
        {"transcript_id": TID, "position": 35, "source": "gnomad", "response_mode": "standard"},
    )

    evidence = data["positions"][0]["variant_evidence"]
    gnomad = evidence["residue_level"]["gnomad"]
    assert gnomad["available"] is False
    assert "variant_count" not in gnomad
    homologs = evidence["meta_domain_homolog_aggregate"]
    assert homologs["available"] is False
    assert "gnomad" not in homologs


async def test_null_domain_mapping_is_unavailable_not_a_homolog_zero(
    facade: Any, call_tool: Any
) -> None:
    """A Pfam membership without a usable aggregate must not manufacture a zero count."""
    data = await call_tool(
        facade,
        "get_variant_counts",
        {"transcript_id": TID, "position": 357, "source": "gnomad", "response_mode": "standard"},
    )

    evidence = data["positions"][0]["variant_evidence"]
    assert evidence["residue_level"]["gnomad"]["available"] is False
    homologs = evidence["meta_domain_homolog_aggregate"]
    assert homologs["available"] is False
    assert "gnomad" not in homologs


async def test_position_view_hides_unscoped_upstream_variant_fields(
    facade: Any, call_tool: Any
) -> None:
    """The position view keeps only explicitly-scoped variant evidence."""
    data = await call_tool(
        facade,
        "get_position_tolerance",
        {"transcript_id": TID, "position": 175, "response_mode": "standard"},
    )

    membership = data["domains"]["PF00870"]
    assert membership == {"meta_domain_homolog_aggregate_available": True}
    assert "normal_variant_count" not in membership
    assert "pathogenic_variant_count" not in membership
    assert "ClinVar" not in data


async def test_region_summary_labels_homolog_aggregates_and_actual_clinvar(
    facade: Any, call_tool: Any
) -> None:
    """Region sums cannot be presented as transcript-residue gnomAD/ClinVar counts."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "response_mode": "standard"},
    )

    assert data["regions"]
    for region in data["regions"]:
        assert "gnomad_variant_count" not in region
        assert "clinvar_variant_count" not in region
        evidence = region["variant_evidence"]
        assert evidence["residue_level"]["gnomad"]["available"] is False
        assert isinstance(evidence["residue_level"]["clinvar"]["variant_count"], int)
        assert "other genes" in evidence["meta_domain_homolog_aggregate"]["provenance"]


def test_budget_truncation_reconciles_pagination_to_actual_rows() -> None:
    """A shaped page resumes at its first omitted row, without inventing returned rows."""
    payload = {
        "positions": [{"protein_pos": position, "detail": "x" * 120} for position in range(10, 30)],
        "pagination": {
            "total": 50,
            "returned": 20,
            "limit": 20,
            "offset": 10,
            "truncated": True,
            "next_offset": 30,
        },
    }
    result = char_budget_guard(payload, max_chars=len(json.dumps(payload)) - 800)

    rows = result["positions"]
    block = result["pagination"]
    assert 0 < len(rows) < 20
    assert rows == payload["positions"][: len(rows)]
    assert block["returned"] == len(rows)
    assert block["truncated"] is True
    assert block["next_offset"] == block["offset"] + len(rows)


async def test_envelope_applies_honest_pagination_after_budget_shaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real MCP envelope preserves the shaped page contract, not just the helper."""
    payload = {
        "positions": [{"protein_pos": position, "detail": "x" * 120} for position in range(1, 21)],
        "pagination": {
            "total": 30,
            "returned": 20,
            "limit": 20,
            "offset": 0,
            "truncated": True,
            "next_offset": 20,
        },
        "_meta": {
            "next_commands": [
                {
                    "tool": "get_variant_counts",
                    "arguments": {"transcript_id": TID, "limit": 20, "offset": 20},
                }
            ]
        },
    }
    monkeypatch.setattr(
        "metadome_link.mcp.envelope.MAX_RESPONSE_CHARS", len(json.dumps(payload)) - 800
    )

    async def call() -> dict[str, Any]:
        return payload

    result = await run_mcp_tool(
        "get_variant_counts",
        call,
        context=McpErrorContext(
            "get_variant_counts",
            response_mode="full",
            arguments={"transcript_id": TID, "limit": 20, "offset": 0},
        ),
    )
    rows = result["positions"]
    block = result["pagination"]
    assert block["returned"] == len(rows)
    assert block["next_offset"] == len(rows)
    page_command = next(
        command
        for command in result["_meta"]["next_commands"]
        if command["tool"] == "get_variant_counts"
    )
    assert page_command["arguments"]["offset"] == len(rows)


async def test_envelope_keeps_nested_meta_domain_forward_page_from_skipping_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shaped homolog-variant page suggests an offset no later than any omission."""
    variants = [{"gene_name": "GENE", "detail": "x" * 120} for _ in range(20)]
    payload = {
        "meta_domains": {
            "PF00001": {
                "normal_variants": variants,
                "pathogenic_variants": variants,
                "pagination": {
                    "normal_variants": {
                        "total": 30,
                        "returned": 20,
                        "limit": 20,
                        "offset": 0,
                        "truncated": True,
                        "next_offset": 20,
                    },
                    "pathogenic_variants": {
                        "total": 30,
                        "returned": 20,
                        "limit": 20,
                        "offset": 0,
                        "truncated": True,
                        "next_offset": 20,
                    },
                },
            }
        },
        "_meta": {
            "next_commands": [
                {
                    "tool": "get_meta_domain",
                    "arguments": {"transcript_id": TID, "position": 175, "offset": 20},
                }
            ]
        },
    }
    monkeypatch.setattr(
        "metadome_link.mcp.envelope.MAX_RESPONSE_CHARS", len(json.dumps(payload)) - 800
    )

    async def call() -> dict[str, Any]:
        return payload

    result = await run_mcp_tool(
        "get_meta_domain",
        call,
        context=McpErrorContext(
            "get_meta_domain",
            response_mode="full",
            arguments={"transcript_id": TID, "position": 175, "offset": 0},
        ),
    )
    block = result["meta_domains"]["PF00001"]["pagination"]
    omitted_offsets = [
        page["next_offset"]
        for page in block.values()
        if page["truncated"] and page["next_offset"] is not None
    ]
    page_command = next(
        command
        for command in result["_meta"]["next_commands"]
        if command["tool"] == "get_meta_domain"
    )
    assert page_command["arguments"]["offset"] == min(omitted_offsets)


@pytest.mark.parametrize(
    ("tool", "arguments", "answer_key"),
    [
        ("get_position_tolerance", {"position": 175}, "sw_dn_ds"),
        ("get_variant_counts", {"position": 175}, "positions"),
        ("compare_positions", {"positions": [175]}, "comparison"),
        ("get_tolerance_landscape", {"limit": 1}, "positional_annotation"),
        ("summarize_intolerant_regions", {}, "regions"),
    ],
)
async def test_minimal_mode_retains_each_audit_tool_core_answer(
    facade: Any,
    call_tool: Any,
    tool: str,
    arguments: dict[str, Any],
    answer_key: str,
) -> None:
    """The repaired minimal mode remains a usable answer, never success:true emptiness."""
    data = await call_tool(
        facade,
        tool,
        {"transcript_id": TID, **arguments, "response_mode": "minimal"},
    )

    assert data["success"] is True
    assert answer_key in data
    assert data[answer_key] not in (None, [], {})
