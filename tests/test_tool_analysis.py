"""Tests for the summarize_intolerant_regions MCP tool (Task 13).

Exercises the full MCP path: facade → envelope → analysis tool body →
injected (respx-mocked) service.  The fixture landscape (result_TP53.json) has
exactly ONE contiguous run of length >= 3 below threshold=0.5: positions
173-177.  All tests target that known ground truth.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# Constants from conftest.py (re-used to construct fixture-specific scenarios)
# ---------------------------------------------------------------------------

BASE = "https://stuart.radboudumc.nl/metadome/api"
TID = "ENST00000269305.4"


# ---------------------------------------------------------------------------
# Happy path - ranked intolerant regions with domain overlap + counts
# ---------------------------------------------------------------------------


async def test_summarize_intolerant_regions_success(facade: Any, call_tool: Any) -> None:
    """summarize_intolerant_regions returns ranked runs with domain/count annotations."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID},
    )
    assert data["success"] is True
    assert data["transcript_id"] == TID
    assert isinstance(data["regions"], list)
    assert len(data["regions"]) >= 1


async def test_summarize_intolerant_regions_contains_173_177(facade: Any, call_tool: Any) -> None:
    """The p.173-177 run is present and fully covered by at least one region."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "threshold": 0.5, "min_run": 3},
    )
    assert data["success"] is True
    covered: set[int] = set()
    for region in data["regions"]:
        covered.update(range(region["start"], region["stop"] + 1))
    assert {173, 174, 175, 176, 177} <= covered, (
        f"Expected p.173-177 to be covered; covered={sorted(covered)}"
    )


async def test_summarize_intolerant_regions_mean_below_threshold(
    facade: Any, call_tool: Any
) -> None:
    """Every returned region has mean_sw_dn_ds strictly below the threshold."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "threshold": 0.5},
    )
    assert data["success"] is True
    for region in data["regions"]:
        assert region["mean_sw_dn_ds"] < 0.5, (
            f"Region {region['start']}-{region['stop']} has "
            f"mean_sw_dn_ds={region['mean_sw_dn_ds']} which is not below 0.5"
        )


async def test_summarize_intolerant_regions_domain_overlap(
    facade: Any, call_tool: Any
) -> None:
    """At least one region overlaps PF00870 (the p53 DNA-binding domain, aa 95-288)."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID},
    )
    assert data["success"] is True
    annotated = any("PF00870" in r.get("domains", []) for r in data["regions"])
    assert annotated, (
        "Expected at least one region to have PF00870 domain overlap; "
        f"regions={[r.get('domains') for r in data['regions']]}"
    )


async def test_summarize_intolerant_regions_counts_present(
    facade: Any, call_tool: Any
) -> None:
    """Every region carries gnomad_variant_count and clinvar_variant_count."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID},
    )
    assert data["success"] is True
    for region in data["regions"]:
        assert "gnomad_variant_count" in region
        assert "clinvar_variant_count" in region
        assert isinstance(region["gnomad_variant_count"], int)
        assert isinstance(region["clinvar_variant_count"], int)


async def test_summarize_intolerant_regions_recommended_citation(
    facade: Any, call_tool: Any
) -> None:
    """Payload carries recommended_citation."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID},
    )
    assert data["success"] is True
    assert "recommended_citation" in data
    assert data["recommended_citation"]


async def test_summarize_intolerant_regions_meta_next_commands(
    facade: Any, call_tool: Any
) -> None:
    """compact response_mode includes _meta.next_commands."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "response_mode": "compact"},
    )
    assert data["success"] is True
    meta = data.get("_meta", {})
    assert "next_commands" in meta
    assert isinstance(meta["next_commands"], list)
    assert len(meta["next_commands"]) >= 1


async def test_summarize_intolerant_regions_region_fields(
    facade: Any, call_tool: Any
) -> None:
    """Each region entry carries the required structural fields."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID},
    )
    assert data["success"] is True
    for region in data["regions"]:
        assert "start" in region
        assert "stop" in region
        assert "length" in region
        assert "mean_sw_dn_ds" in region
        assert "domains" in region
        assert isinstance(region["domains"], list)
        assert region["length"] == region["stop"] - region["start"] + 1


# ---------------------------------------------------------------------------
# Respects top_n parameter
# ---------------------------------------------------------------------------


async def test_summarize_intolerant_regions_top_n_one(facade: Any, call_tool: Any) -> None:
    """top_n=1 returns at most 1 region."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "top_n": 1},
    )
    assert data["success"] is True
    assert len(data["regions"]) <= 1


async def test_summarize_intolerant_regions_respects_min_run(
    facade: Any, call_tool: Any
) -> None:
    """min_run=6 excludes the p.173-177 run (length 5); returns no regions."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "threshold": 0.5, "min_run": 6, "response_mode": "standard"},
    )
    assert data["success"] is True
    # p.173-177 has length 5; with min_run=6 it is excluded
    # Use standard mode so empty regions list is preserved (compact drops empty lists)
    covered: set[int] = set()
    for region in data.get("regions", []):
        covered.update(range(region["start"], region["stop"] + 1))
    assert 175 not in covered, (
        f"Expected p.175 to be excluded with min_run=6; covered={sorted(covered)}"
    )


async def test_summarize_intolerant_regions_ranked_ascending(
    facade: Any, call_tool: Any
) -> None:
    """Regions are ranked by mean_sw_dn_ds ascending (most constrained first)."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "min_run": 1},  # allow short runs for more regions
    )
    assert data["success"] is True
    scores = [r["mean_sw_dn_ds"] for r in data["regions"]]
    assert scores == sorted(scores), f"Regions not sorted ascending: {scores}"


# ---------------------------------------------------------------------------
# Envelope / schema fields
# ---------------------------------------------------------------------------


async def test_summarize_intolerant_regions_envelope_fields(
    facade: Any, call_tool: Any
) -> None:
    """Payload includes threshold, min_run, top_n echo and region_count."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "threshold": 0.45, "min_run": 3, "top_n": 5},
    )
    assert data["success"] is True
    assert data["threshold"] == pytest.approx(0.45)
    assert data["min_run"] == 3
    assert data["top_n"] == 5


# ---------------------------------------------------------------------------
# Not-built landscape → not_found / switch_tool
# ---------------------------------------------------------------------------


@respx.mock
async def test_summarize_intolerant_regions_not_found(
    call_tool: Any,
    facade: Any,
) -> None:
    """A transcript whose landscape is not built returns error_code=not_found."""
    # Use a transcript id not in the fixture cache; mock the upstream to return PENDING
    unknown_tid = "ENST00000000001.1"
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": unknown_tid})
    )
    respx.get(f"{BASE}/status/{unknown_tid}/").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": unknown_tid},
    )
    assert data["success"] is False
    assert data["error_code"] == "not_found"
    assert data["recovery_action"] == "switch_tool"


async def test_summarize_intolerant_regions_invalid_transcript_id(
    facade: Any, call_tool: Any
) -> None:
    """An unversioned transcript id returns error_code=invalid_input."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": "ENST00000269305"},  # missing .N suffix
    )
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"
