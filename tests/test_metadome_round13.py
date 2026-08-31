"""Round-13 regressions for the final MetaDome review findings."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.api.models import validate_result_document
from metadome_link.config import ServerSettings
from metadome_link.constants import DATA_PROFILES
from metadome_link.exceptions import UpstreamSchemaError
from metadome_link.mcp import schemas
from metadome_link.mcp.capabilities import build_capabilities, capabilities_version

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "metadome"
BASE = "https://www.metadome.app/metadome/api"
TID = "ENST00000269305.9"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
async def test_endpoint6_requires_every_requested_domain() -> None:
    respx.post(f"{BASE}/get_metadomain_annotation/").mock(return_value=httpx.Response(200, json={}))
    client = MetaDomeClient(ServerSettings())
    try:
        with pytest.raises(UpstreamSchemaError):
            await client.get_metadomain_annotation(TID, 175, {"PF00870": [81]})
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: next(
            row["domains"]["PF00870"]
            for row in payload["positional_annotation"]
            if isinstance(row["domains"].get("PF00870"), dict)
        ).update({"normal_missense_variant_count": 3, "normal_variant_count": 2}),
        lambda payload: next(
            row["domains"]["PF00870"]
            for row in payload["positional_annotation"]
            if isinstance(row["domains"].get("PF00870"), dict)
        ).update({"pathogenic_missense_variant_count": 3, "pathogenic_variant_count": 2}),
    ],
)
def test_biological_count_subsets_cannot_exceed_totals(mutator: Any) -> None:
    payload = _load("result_TP53.json")
    mutator(payload)
    with pytest.raises(UpstreamSchemaError):
        validate_result_document(payload)


def test_normal_variant_allele_count_invariant_is_checked_in_metadomain_payload() -> None:
    from metadome_link.api.models import validate_metadomain_blocks

    payload = _load("metadomain_p175.json")
    payload["PF00870"]["normal_variants"][0]["allele_count"] = 3
    payload["PF00870"]["normal_variants"][0]["allele_number"] = 2
    with pytest.raises(UpstreamSchemaError):
        validate_metadomain_blocks(payload)


def test_capabilities_reject_mixed_immutable_profile_components() -> None:
    profile = DATA_PROFILES["GRCh37.p13"]
    versions = dict(profile.data_versions)
    versions["gencode"] = DATA_PROFILES["GRCh38.p14"].data_versions["gencode"]
    with pytest.raises(ValueError, match="immutable profile"):
        build_capabilities(data_versions=versions, data_version=profile.data_version)
    with pytest.raises(ValueError, match="immutable profile"):
        capabilities_version(data_versions=versions, data_version=profile.data_version)


async def test_all_live_tools_advertise_their_output_schemas(facade: Any) -> None:
    from fastmcp import Client

    expected = {
        "get_server_capabilities": schemas.GET_SERVER_CAPABILITIES_SCHEMA,
        "get_diagnostics": schemas.GET_DIAGNOSTICS_SCHEMA,
        "resolve_transcript": schemas.RESOLVE_TRANSCRIPT_SCHEMA,
        "request_tolerance_landscape": schemas.REQUEST_TOLERANCE_LANDSCAPE_SCHEMA,
        "get_tolerance_landscape": schemas.GET_TOLERANCE_LANDSCAPE_SCHEMA,
        "get_position_tolerance": schemas.GET_POSITION_TOLERANCE_SCHEMA,
        "get_variant_counts": schemas.GET_VARIANT_COUNTS_SCHEMA,
        "compare_positions": schemas.COMPARE_POSITIONS_SCHEMA,
        "get_protein_domains": schemas.GET_PROTEIN_DOMAINS_SCHEMA,
        "get_meta_domain": schemas.GET_META_DOMAIN_SCHEMA,
        "summarize_intolerant_regions": schemas.SUMMARIZE_INTOLERANT_REGIONS_SCHEMA,
    }
    async with Client(facade) as client:
        tools = {item.name: item for item in await client.list_tools()}
    assert set(tools) == set(expected)
    for name, schema in expected.items():
        assert tools[name].outputSchema == schema


def test_docs_describe_tool_modes_and_terminal_cached_failures_truthfully() -> None:
    readme = pathlib.Path("README.md").read_text()
    agents = pathlib.Path("AGENTS.md").read_text()
    usage = pathlib.Path("docs/usage.md").read_text()
    architecture = pathlib.Path("docs/architecture.md").read_text()
    assert "Every tool is annotated `READ_ONLY_OPEN_WORLD`" not in readme
    assert "request_tolerance_landscape" in readme and "idempotent" in readme
    assert "_meta = {tool, request_id, data_versions, unsafe_for_clinical_use}" in " ".join(
        agents.split()
    )
    assert "`{tool, request_id, data_versions, unsafe_for_clinical_use}`" in usage
    for text in (usage, architecture):
        row = next(line for line in text.splitlines() if "| `upstream_unavailable` |" in line)
        assert "cached" in row.lower() and "switch_tool" in row
        assert "Celery FAILURE is transient" not in row


def test_api_reference_uses_build_neutral_genomic_positions_and_gene_echo() -> None:
    text = pathlib.Path("docs/research/03-metadome-api.md").read_text()
    assert "pretty hg19 genomic span" not in text
    assert "requested build (GRCh37.p13 or GRCh38.p14)" in text
    assert "For a nonempty response, `gene_name` is present and matches" in " ".join(text.split())
