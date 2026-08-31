"""Round-14 regression tests for final MetaDome contract findings."""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError

from metadome_link.api.client import MetaDomeClient
from metadome_link.api.models import validate_result_document
from metadome_link.config import CacheSettings, MetaDomeSettings, ServerSettings
from metadome_link.exceptions import UpstreamSchemaError
from metadome_link.mcp import schemas

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "metadome"
BASE = "https://www.metadome.app/metadome/api"
TID = "ENST00000269305.9"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _domain_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    for row in payload["positional_annotation"]:
        mapping = row["domains"].get("PF00870")
        if isinstance(mapping, dict):
            return mapping
    raise AssertionError("fixture missing PF00870")


def test_clinsig_breakdowns_are_bounded_and_cross_consistent() -> None:
    payload = _load("result_TP53.json")
    mapping = _domain_mapping(payload)
    mapping["pathogenic_variant_count"] = 3
    mapping["pathogenic_missense_variant_count"] = 1
    mapping["pathogenic_variant_count_per_clinsig"] = {"Pathogenic": 2}
    mapping["pathogenic_missense_variant_count_per_clinsig"] = {"Pathogenic": 2}
    with pytest.raises(UpstreamSchemaError):
        validate_result_document(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_response_bytes", True),
        ("max_response_bytes", 10**100),
        ("max_retries", "2.5"),
        ("politeness_burst", False),
    ],
)
def test_critical_integer_settings_are_strict_and_bounded(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        MetaDomeSettings(**{field: value})


@pytest.mark.parametrize("field", ["ttl_transcripts_s", "lru_results", "lru_transcripts"])
@pytest.mark.parametrize("value", [True, "2.5", -1, 10**100])
def test_cache_integer_settings_are_strict_and_bounded(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        CacheSettings(**{field: value})


def test_nested_integer_environment_values_accept_decimal_strings(monkeypatch: Any) -> None:
    monkeypatch.setenv("METADOME_LINK_METADOME__MAX_RETRIES", "2")
    monkeypatch.setenv("METADOME_LINK_CACHE__LRU_TRANSCRIPTS", "12")
    settings = ServerSettings(_env_file=None)
    assert settings.metadome.max_retries == 2
    assert settings.cache.lru_transcripts == 12


@respx.mock
async def test_transcript_cache_hits_expires_and_returns_immutable_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = respx.get(f"{BASE}/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(200, json=_load("get_transcripts_TP53.json"))
    )
    settings = ServerSettings(cache={"ttl_transcripts_s": 10, "lru_transcripts": 2}, _env_file=None)
    client = MetaDomeClient(settings)
    clock = __import__("time").monotonic()
    monkeypatch.setattr("metadome_link.api.client.time.monotonic", lambda: clock)
    try:
        first = await client.get_transcripts("TP53")
        first[0]["gencode_id"] = "MUTATED"
        assert (await client.get_transcripts("TP53"))[0]["gencode_id"] != "MUTATED"
        assert route.call_count == 1
        clock += 11
        await client.get_transcripts("TP53")
        assert route.call_count == 2
    finally:
        await client.aclose()


@respx.mock
async def test_transcript_cache_deduplicates_concurrent_identity_requests() -> None:
    route = respx.get(f"{BASE}/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(200, json=_load("get_transcripts_TP53.json"))
    )
    settings = ServerSettings(cache={"ttl_transcripts_s": 60, "lru_transcripts": 2}, _env_file=None)
    client = MetaDomeClient(settings)
    try:
        results = await asyncio.gather(*(client.get_transcripts("TP53") for _ in range(5)))
        assert all(result == results[0] for result in results)
        assert route.call_count == 1
    finally:
        await client.aclose()


def test_examples_are_current_and_safe() -> None:
    local = pathlib.Path(".env.example").read_text()
    docker = pathlib.Path(".env.docker.example").read_text()
    assert "METADOME_LINK_HOST=127.0.0.1" in local
    assert "https://www.metadome.app/metadome/api" in local
    assert "stuart.radboudumc.nl" not in local
    assert "METADOME_LINK_HOST=0.0.0.0" in docker
    assert "METADOME_LINK_ALLOW_PUBLIC_BIND=true" in docker
    assert "https://www.metadome.app/metadome/api" in docker
    assert "stuart.radboudumc.nl" not in docker


def test_docker_build_metadata_reaches_runtime_environment() -> None:
    dockerfile = pathlib.Path("docker/Dockerfile").read_text()
    assert 'METADOME_LINK_GIT_SHA="${VCS_REF}"' in dockerfile
    assert 'METADOME_LINK_BUILT_AT="${BUILD_DATE}"' in dockerfile


def test_output_schemas_reject_known_shape_mismatches() -> None:
    import jsonschema

    jsonschema.validate({"success": True, "domains": {}}, schemas.GET_POSITION_TOLERANCE_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"success": True, "domain_ids": []}, schemas.GET_POSITION_TOLERANCE_SCHEMA
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"success": True, "total": 1}, schemas.RESOLVE_TRANSCRIPT_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"success": True, "region_count": 1}, schemas.SUMMARIZE_INTOLERANT_REGIONS_SCHEMA
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"success": True, "domains": [{"id": "PF00870"}]}, schemas.GET_PROTEIN_DOMAINS_SCHEMA
        )


def test_citation_does_not_claim_residue_level_gnomad_counts() -> None:
    text = pathlib.Path("CITATION.cff").read_text()
    assert "per-residue gnomAD counts" not in text
