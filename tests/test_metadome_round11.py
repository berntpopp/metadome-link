"""Round-11 adversarial tests for the final MetaDome review findings."""

from __future__ import annotations

import json
import math
import pathlib
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from metadome_link.api.client import MetaDomeClient
from metadome_link.api.models import (
    validate_metadomain_blocks,
    validate_result_document,
    validate_transcript_entries,
)
from metadome_link.api.response import parse_json_text
from metadome_link.config import MetaDomeSettings, ServerSettings
from metadome_link.constants import MAX_GENOMIC_POSITION
from metadome_link.exceptions import (
    InvalidInputError,
    UpstreamSchemaError,
)
from metadome_link.services.landscape import intolerant_runs
from metadome_link.services.landscape_views import resolve_meta_domain_request
from metadome_link.services.selectors import require_complete_range
from metadome_link.services.shaping import char_budget_guard

TID = "ENST00000269305.9"
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "metadome"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _first_domain(result: dict[str, Any]) -> dict[str, Any]:
    for row in result["positional_annotation"]:
        for mapping in row["domains"].values():
            if isinstance(mapping, dict):
                return mapping
    raise AssertionError("fixture has no domain mapping")


@pytest.mark.parametrize("start,stop", [(None, 177), (173, None), (177, 173)])
def test_ranges_are_complete_and_ordered(start: int | None, stop: int | None) -> None:
    with pytest.raises(InvalidInputError):
        require_complete_range(start, stop)


def test_reversed_slice_does_not_swap() -> None:
    from metadome_link.services.landscape import slice_positions

    with pytest.raises(InvalidInputError):
        slice_positions(_load("result_TP53.json"), 177, 173)


@pytest.mark.parametrize(
    "field,value", [("aa_length", 10**100), ("aa_length", MAX_GENOMIC_POSITION + 1)]
)
def test_transcript_numeric_fields_are_bounded(field: str, value: int) -> None:
    payload = _load("get_transcripts_TP53.json")
    payload["transcript_ids"][0][field] = value
    with pytest.raises(UpstreamSchemaError):
        validate_transcript_entries(payload["transcript_ids"])


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p["positional_annotation"][0].__setitem__("sw_dn_ds", 10**100),
        lambda p: p["domains"][0].__setitem__("normal_variant_count", 10**100),
        lambda p: p["domains"][0].__setitem__("normal_variant_count", 1e100),
        lambda p: _first_domain(p).__setitem__("pathogenic_variant_count", 10**100),
        lambda p: next(row for row in p["positional_annotation"] if row.get("ClinVar"))["ClinVar"][
            0
        ].__setitem__("clinvar_ID", "9" * 100),
    ],
)
def test_result_all_numeric_fields_have_finite_semantic_caps(mutator: Any) -> None:
    payload = _load("result_TP53.json")
    mutator(payload)
    with pytest.raises(UpstreamSchemaError):
        validate_result_document(payload)


def test_metadomain_numeric_fields_have_finite_semantic_caps() -> None:
    payload = _load("metadomain_p175.json")
    payload["PF00870"]["normal_variants"][0]["protein_pos"] = 10**100
    with pytest.raises(UpstreamSchemaError):
        validate_metadomain_blocks(payload)


@pytest.mark.parametrize("field", ["start", "stop"])
def test_oversized_domain_error_names_offending_bound(field: str) -> None:
    payload = _load("result_TP53.json")
    payload["domains"][0][field] = 1_000_001
    with pytest.raises(UpstreamSchemaError) as caught:
        validate_result_document(payload)
    assert caught.value.extra["field"].endswith(f".{field}")


@pytest.mark.parametrize("value", [True, "0.5", math.nan, math.inf, 0, -1, 10**100])
def test_threshold_service_helper_is_strict(value: object) -> None:
    with pytest.raises(InvalidInputError):
        intolerant_runs(_load("result_TP53.json"), threshold=value, min_run=3, top_n=5)


@pytest.mark.parametrize(
    "field",
    [
        "request_timeout_s",
        "poll_soft_deadline_s",
        "poll_initial_interval_s",
        "poll_max_interval_s",
        "politeness_rate_per_s",
    ],
)
@pytest.mark.parametrize("value", [True, "1", math.nan, math.inf, 0, -1, 10**100])
def test_float_settings_reject_coercion_and_unbounded_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        MetaDomeSettings(**{field: value})


def test_omitted_domains_are_validated_like_explicit_domains() -> None:
    landscape = _load("result_TP53.json")
    mapping = next(
        membership
        for row in landscape["positional_annotation"]
        if row.get("protein_pos") == 175
        for membership in row["domains"].values()
        if isinstance(membership, dict)
    )
    mapping["consensus_pos"] = [MAX_GENOMIC_POSITION + 1]
    with pytest.raises(InvalidInputError):
        resolve_meta_domain_request(landscape, 175, None)


def test_response_budget_is_hard_after_dropped_summary() -> None:
    payload = {"items": ["x" * 50 for _ in range(20)], "pagination": {"total": 20}}
    shaped = char_budget_guard(payload, max_chars=300)
    assert len(json.dumps(shaped, separators=(",", ":"))) <= 300


def test_fixture_is_strictly_loadable_and_duplicate_keys_fail() -> None:
    parse_json_text((FIXTURES / "get_transcripts_TP53.json").read_text())
    with pytest.raises(UpstreamSchemaError):
        parse_json_text('{"genome_build":"GRCh38.p14","genome_build":"GRCh37.p13"}')


@pytest.mark.parametrize(
    "position,domains",
    [
        (True, {"PF00870": [81]}),
        (1_000_001, {"PF00870": [81]}),
        (175, None),
        (175, {"PF00870": [True]}),
    ],
)
async def test_endpoint6_client_validates_request_before_network(
    mocked_metadome: Any, position: object, domains: object
) -> None:
    client = MetaDomeClient(ServerSettings())
    try:
        with pytest.raises(InvalidInputError):
            await client.get_metadomain_annotation(TID, position, domains)  # type: ignore[arg-type]
        assert not mocked_metadome.calls
    finally:
        await client.aclose()


async def test_transcript_response_gene_is_bound_to_request(mocked_metadome: Any) -> None:
    body = _load("get_transcripts_TP53.json")
    body["gene_name"] = "BRCA1"
    mocked_metadome.get("/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(200, json=body)
    )
    client = MetaDomeClient(ServerSettings())
    try:
        with pytest.raises(UpstreamSchemaError):
            await client.get_transcripts("TP53")
    finally:
        await client.aclose()


async def test_ranged_landscape_page_and_continuation_preserve_slice(
    facade: Any, call_tool: Any
) -> None:
    data = await call_tool(
        facade,
        "get_tolerance_landscape",
        {
            "transcript_id": TID,
            "position_start": 173,
            "position_stop": 177,
            "limit": 2,
            "offset": 2,
        },
    )
    assert [row["protein_pos"] for row in data["positional_annotation"]] == [175, 176]
    assert data["pagination"]["total"] == 5
    assert data["pagination"]["next_offset"] == 4
    next_command = next(
        command
        for command in data["_meta"]["next_commands"]
        if command["tool"] == "get_tolerance_landscape"
    )
    assert next_command["arguments"] == {
        "transcript_id": TID,
        "position_start": 173,
        "position_stop": 177,
        "limit": 2,
        "offset": 4,
    }


async def test_default_discovery_summary_contains_profile_identity(
    facade: Any, call_tool: Any
) -> None:
    data = await call_tool(facade, "get_server_capabilities", {})
    assert data["genome_build"] == "GRCh38.p14"
    assert data["data_version"]


async def test_threshold_schema_uses_standard_json_schema_keywords(facade: Any) -> None:
    from fastmcp import Client

    async with Client(facade) as client:
        tool = next(
            item
            for item in await client.list_tools()
            if item.name == "summarize_intolerant_regions"
        )
    threshold = tool.inputSchema["properties"]["threshold"]
    assert threshold["exclusiveMinimum"] == 0.0
    assert threshold["maximum"] == 2.0
    assert "gt" not in threshold and "le" not in threshold
