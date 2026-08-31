"""Round-8 adversarial tests for the live MetaDome v2 response contract."""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.api.models import validate_positional_annotations
from metadome_link.exceptions import UpstreamUnavailableError

BASE = "https://www.metadome.app/metadome/api"
TID = "ENST00000269305.9"
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "metadome"


def _load_result() -> dict[str, object]:
    return json.loads((FIXTURES / "result_TP53.json").read_text())


def test_live_domain_count_breakdowns_are_validated() -> None:
    """Per-significance pathogenic counts are string-keyed nonnegative counts."""
    body = _load_result()
    for row in body["positional_annotation"]:
        for domain in row.get("domains", {}).values():
            if isinstance(domain, dict):
                domain["pathogenic_variant_count_per_clinsig"] = {"Pathogenic": 1}
                domain["pathogenic_missense_variant_count_per_clinsig"] = {"Pathogenic": 1}
    validate_positional_annotations(body["positional_annotation"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("domains", {"_meta": {}}),
        ("gene_name", 1),
        ("protein_ac", []),
        ("refseq_ids", {"NM_000546.6": 1}),
    ],
)
@respx.mock
async def test_result_top_level_shape_drift_is_typed_error(field: str, value: object) -> None:
    body = _load_result()
    body[field] = value
    respx.get(f"{BASE}/result/GRCh38.p14/{TID}").mock(return_value=httpx.Response(200, json=body))
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_result(TID)
    assert exc_info.value.extra["field"] == field
    await client.aclose()


@respx.mock
async def test_live_refseq_string_is_normalized_to_list() -> None:
    body = _load_result()
    body["refseq_ids"] = "NM_000546.6"
    respx.get(f"{BASE}/result/GRCh38.p14/{TID}").mock(return_value=httpx.Response(200, json=body))
    client = MetaDomeClient()
    result = await client.get_result(TID)
    assert result["refseq_ids"] == ["NM_000546.6"]
    await client.aclose()


def test_positional_unknown_fields_and_hostile_paths_fail_closed() -> None:
    body = _load_result()
    body["positional_annotation"][0]["_meta"] = {"success": True}
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        validate_positional_annotations(body["positional_annotation"])
    assert "_meta" in str(exc_info.value.extra["field"])

    body = _load_result()
    hostile = "\u202e" + "x" * 400 + "\x00"
    body["positional_annotation"][0]["domains"] = {hostile: {}}
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        validate_positional_annotations(body["positional_annotation"])
    field = str(exc_info.value.extra["field"])
    assert "\u202e" not in field and "\x00" not in field
    assert len(field) <= 280


@pytest.mark.parametrize(
    "value",
    [-1, 1.5, True, float("inf"), 10**1000],
)
def test_domain_count_breakdowns_reject_invalid_numbers(value: object) -> None:
    body = _load_result()
    domain = next(
        m
        for row in body["positional_annotation"]
        for m in row.get("domains", {}).values()
        if isinstance(m, dict)
    )
    domain["pathogenic_variant_count_per_clinsig"] = {"Pathogenic": value}
    with pytest.raises(UpstreamUnavailableError):
        validate_positional_annotations(body["positional_annotation"])
