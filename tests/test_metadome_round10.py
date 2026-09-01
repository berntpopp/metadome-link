"""Round-10 adversarial tests for finite coordinate and analysis bounds."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from metadome_link.api.models import validate_metadomain_blocks, validate_result_document
from metadome_link.constants import MAX_GENOMIC_POSITION
from metadome_link.exceptions import UpstreamUnavailableError

TID = "ENST00000269305.9"
# The review contract needs an explicit finite protein-coordinate cap. Keep the
# expected value local until the production constant is introduced below.
EXPECTED_MAX_PROTEIN_POSITION = 1_000_000
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "metadome"


def _load(name: str) -> dict[str, Any]:
    """Load a captured response without sharing mutable fixture state."""
    return json.loads((FIXTURES / name).read_text())


def _first_domain(result: dict[str, Any]) -> dict[str, Any]:
    for row in result["positional_annotation"]:
        for mapping in row["domains"].values():
            if isinstance(mapping, dict):
                return mapping
    raise AssertionError("fixture has no populated domain mapping")


@pytest.mark.parametrize("value", [MAX_GENOMIC_POSITION + 1, 10**100])
def test_response_consensus_positions_have_a_finite_central_bound(value: int) -> None:
    """Response consensus coordinates cannot exceed the shared genomic cap."""
    result = _load("result_TP53.json")
    _first_domain(result)["consensus_pos"] = [value]
    with pytest.raises(UpstreamUnavailableError):
        validate_result_document(result)


@pytest.mark.parametrize("value", [EXPECTED_MAX_PROTEIN_POSITION + 1, 10**100])
def test_response_protein_positions_have_a_finite_central_bound(value: int) -> None:
    """Landscape protein positions cannot carry unbounded integers."""
    result = _load("result_TP53.json")
    result["positional_annotation"][0]["protein_pos"] = value
    with pytest.raises(UpstreamUnavailableError):
        validate_result_document(result)


@pytest.mark.parametrize("field", ["start", "stop"])
def test_response_domain_bounds_have_a_finite_central_bound(field: str) -> None:
    """Top-level domain protein coordinates use the same explicit cap."""
    result = _load("result_TP53.json")
    result["domains"][0][field] = EXPECTED_MAX_PROTEIN_POSITION + 1
    with pytest.raises(UpstreamUnavailableError):
        validate_result_document(result)


@pytest.mark.parametrize("value", [EXPECTED_MAX_PROTEIN_POSITION + 1, 10**100])
def test_response_metadomain_variant_positions_have_a_finite_bound(value: int) -> None:
    """Endpoint-six variant protein positions cannot escape the shared cap."""
    payload = _load("metadomain_p175.json")
    payload["PF00870"]["normal_variants"][0]["protein_pos"] = value
    with pytest.raises(UpstreamUnavailableError):
        validate_metadomain_blocks(payload)


@pytest.mark.parametrize("threshold", [True, "0.5", float("nan"), float("inf")])
async def test_summarize_threshold_rejects_non_strict_or_nonfinite_values(
    facade: Any, call_tool: Any, threshold: object
) -> None:
    """The MCP boundary rejects coercive and non-finite threshold values."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "threshold": threshold},
    )
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


async def test_summarize_threshold_accepts_strict_finite_integer(
    facade: Any, call_tool: Any
) -> None:
    """An integer threshold is a valid finite real-number input."""
    data = await call_tool(
        facade,
        "summarize_intolerant_regions",
        {"transcript_id": TID, "threshold": 1},
    )
    assert data["success"] is True
