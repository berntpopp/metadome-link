"""Round-8 adversarial tests for the live MetaDome v2 response contract."""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.api.models import (
    validate_metadomain_blocks,
    validate_positional_annotations,
    validate_result_document,
)
from metadome_link.api.response import parse_json
from metadome_link.exceptions import UpstreamUnavailableError

BASE = "https://www.metadome.app/metadome/api"
TID = "ENST00000269305.9"
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "metadome"


def _load_result() -> dict[str, object]:
    return json.loads((FIXTURES / "result_TP53.json").read_text())


def _load_metadomain() -> dict[str, object]:
    """Load the captured endpoint-6 payload without sharing mutable state."""
    return json.loads((FIXTURES / "metadomain_p175.json").read_text())


def _first_clinvar(body: dict[str, object]) -> dict[str, object]:
    """Return a captured positional ClinVar record for mutation tests."""
    for row in body["positional_annotation"]:
        if row.get("ClinVar"):
            return row["ClinVar"][0]
    raise AssertionError("fixture has no positional ClinVar record")


@pytest.mark.parametrize(
    "field",
    ["transcript_id", "gene_name", "protein_ac", "refseq_ids", "domains", "positional_annotation"],
)
def test_result_requires_all_success_fields(field: str) -> None:
    """A cached result cannot be accepted when any required identity/data field is absent."""
    body = _load_result()
    del body[field]
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        validate_result_document(body)
    assert exc_info.value.extra["field"] == field


@pytest.mark.parametrize("unknown", ["_meta", "success", "error_code"])
def test_metadomain_blocks_reject_envelope_fields(unknown: str) -> None:
    """Endpoint-6 data blocks may not carry MCP envelope/control fields."""
    body = _load_metadomain()
    body["PF00870"][unknown] = True
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        validate_metadomain_blocks(body)
    assert exc_info.value.extra["field"] == "PF00870"


@pytest.mark.parametrize("field", ["alignment_depth", "clinvar_pos"])
def test_endpoint_six_bounded_integer_fields_reject_huge_values(field: str) -> None:
    """Alignment/deep genomic positions stay finite and within documented bounds."""
    if field == "alignment_depth":
        body = _load_metadomain()
        body["PF00870"][field] = 10**1000
        with pytest.raises(UpstreamUnavailableError):
            validate_metadomain_blocks(body)
        return
    body = _load_result()
    _first_clinvar(body)["pos"] = 10**1000
    with pytest.raises(UpstreamUnavailableError):
        validate_result_document(body)


@pytest.mark.parametrize("field,value", [("strand", "?"), ("type", "frameshift")])
def test_documented_variant_enums_are_enforced(field: str, value: str) -> None:
    """Variant and strand discriminators are closed enums at both API boundaries."""
    result = _load_result()
    result["positional_annotation"][0]["strand"] = value if field == "strand" else "-"
    if field == "type":
        _first_clinvar(result)[field] = value
    with pytest.raises(UpstreamUnavailableError):
        validate_result_document(result)

    metadomain = _load_metadomain()
    variant = metadomain["PF00870"]["normal_variants"][0]
    variant[field] = value
    with pytest.raises(UpstreamUnavailableError):
        validate_metadomain_blocks(metadomain)


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


def test_json_parser_accepts_valid_surrogate_pair_scalar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid UTF-16 pair is one Unicode scalar, unlike a lone surrogate."""
    response = httpx.Response(200, content=b"{}")

    def return_pair(_response: httpx.Response, **_kwargs: object) -> object:
        return {"status": "\ud83d\ude00"}

    monkeypatch.setattr(httpx.Response, "json", return_pair)
    assert parse_json(response)["status"] == "\ud83d\ude00"


@pytest.mark.parametrize(
    "payload",
    [
        b'{"transcript_id":"ENST00000269305.9","transcript_id":"ENST00000504937.5"}',
        b'{"profile":{"genome_build":"GRCh38.p14","genome_build":"GRCh37.p13"}}',
    ],
)
def test_json_parser_rejects_duplicate_object_members(payload: bytes) -> None:
    """Conflicting top-level identity members cannot use last-key-wins parsing."""
    response = httpx.Response(200, content=payload)
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        parse_json(response)
    assert exc_info.value.extra["field"] == "response_body"


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sw_coverage", 0),
        ("sw_coverage", 0.0),
        ("sw_coverage", False),
        ("sw_coverage", 1.0),
        ("sw_coverage", 1.0001),
        ("sw_size", 9),
        ("sw_size", 10.0),
        ("sw_size", True),
        ("sw_size", 10),
    ],
)
def test_position_numeric_contract_enforces_coverage_and_size(field: str, value: object) -> None:
    """Coverage is in (0,1], while Smith-Waterman size is exactly ten."""
    body = _load_result()
    body["positional_annotation"][0][field] = value
    valid = (field == "sw_coverage" and value == 1.0) or (
        field == "sw_size" and type(value) is int and value == 10
    )
    if valid:
        validate_result_document(body)
    else:
        with pytest.raises(UpstreamUnavailableError) as exc_info:
            validate_result_document(body)
        assert exc_info.value.extra["field"] == f"positional_annotation[0].{field}"


@pytest.mark.parametrize("endpoint", ["status", "result", "error"])
@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b'{"status":"\\ud800"}',
        b'{"\\ud800":"ok"}',
        b'{"status":NaN}',
        b'{"status":Infinity}',
        b'{"status":-Infinity}',
    ],
)
@respx.mock
async def test_invalid_json_is_typed_and_not_retried(endpoint: str, payload: bytes) -> None:
    """All GET endpoints reject malformed Unicode and nonstandard JSON constants."""
    route = respx.get(f"{BASE}/{endpoint}/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, content=payload)
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        if endpoint == "status":
            await client.get_status(TID)
        elif endpoint == "result":
            await client.get_result(TID)
        else:
            await client.get_error(TID)
    assert exc_info.value.retryable is False
    assert exc_info.value.extra["field"] == "response_body"
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_deep_json_recursion_is_typed_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decoder recursion failure cannot escape as a raw exception or retry."""
    route = respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )

    def raise_recursion(_response: httpx.Response, **_kwargs: object) -> object:
        raise RecursionError("JSON nesting exceeded")

    monkeypatch.setattr(httpx.Response, "json", raise_recursion)
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_status(TID)
    assert exc_info.value.retryable is False
    assert exc_info.value.extra["field"] == "response_body"
    assert route.call_count == 1
    await client.aclose()
