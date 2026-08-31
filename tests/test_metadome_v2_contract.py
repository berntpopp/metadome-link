"""MetaDome v2 live-API and provenance contract.

Captured against the public MetaDome 2.0 service and its Zenodo record on
2026-08-31.  The build token is part of every upstream operation: omitting the
``.p14`` suffix returns a plausible HTTP-200 empty transcript list.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.cache.store import ResultCache
from metadome_link.config import ServerSettings
from metadome_link.constants import DATA_VERSIONS, METADOME_DATA_VERSION
from metadome_link.exceptions import UpstreamUnavailableError
from metadome_link.mcp.capabilities import build_capabilities
from metadome_link.mcp.envelope import run_mcp_tool
from metadome_link.mcp.notfound_guard import unknown_tool_envelope
from metadome_link.mcp.service_adapters import set_metadome_service
from metadome_link.services.metadome_service import MetaDomeService

V2_BASE = "https://www.metadome.app/metadome/api"
TID = "ENST00000269305.9"


def test_default_configuration_and_provenance_are_exact_metadome_v2() -> None:
    settings = ServerSettings()

    assert settings.metadome.base_url == V2_BASE
    assert settings.metadome.genome_build == "GRCh38.p14"
    assert METADOME_DATA_VERSION == (
        "metadome2.0-grch38.p14-gencode45-uniprot2025_01-pfam37.4-gnomad4.1-clinvar2025-10-06"
    )
    assert DATA_VERSIONS == {
        "assembly": "GRCh38.p14",
        "gencode": "v45",
        "uniprot": "2025_01",
        "gnomad": "v4.1",
        "clinvar": "2025-10-06",
        "pfam": "37.4",
        "metadome_app": "2.0",
        "data_doi": "10.5281/zenodo.19376150",
    }


@respx.mock
async def test_every_v2_operation_is_bound_to_the_exact_genome_build() -> None:
    transcript = "ENST00000504937.5"
    transcript_route = respx.get(f"{V2_BASE}/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(
            200,
            json={
                "gene_name": "TP53",
                "genome_build": "GRCh38.p14",
                "transcript_ids": [
                    {
                        "aa_length": 261,
                        "gencode_id": transcript,
                        "has_protein_data": True,
                        "mane_transcript_type": "",
                        "refseq_nm_numbers": "NM_001126115.2",
                    }
                ],
            },
        )
    )
    submit_route = respx.post(f"{V2_BASE}/submit_visualization/").mock(
        return_value=httpx.Response(
            200,
            json={"transcript_id": transcript, "genome_build": "GRCh38.p14"},
        )
    )
    status_route = respx.get(f"{V2_BASE}/status/GRCh38.p14/{transcript}").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )
    result_route = respx.get(f"{V2_BASE}/result/GRCh38.p14/{transcript}").mock(
        return_value=httpx.Response(
            200,
            json={"transcript_id": transcript, "domains": [], "positional_annotation": []},
        )
    )
    error_route = respx.get(f"{V2_BASE}/error/GRCh38.p14/{transcript}").mock(
        return_value=httpx.Response(200, json={"error": "build failed"})
    )
    metadomain_route = respx.post(f"{V2_BASE}/get_metadomain_annotation/").mock(
        return_value=httpx.Response(200, json={})
    )

    client = MetaDomeClient()
    normalized = (await client.get_transcripts("TP53"))[0]
    assert normalized["gencode_id"] == transcript
    assert normalized["mane_transcript_type"] == ""
    assert await client.submit_visualization(transcript) == transcript
    assert await client.get_status(transcript) == "SUCCESS"
    assert (await client.get_result(transcript))["transcript_id"] == transcript
    assert (await client.get_error(transcript))["error"] == "build failed"
    assert await client.get_metadomain_annotation(transcript, 1, {"PF00870": [35]}) == {}
    await client.aclose()

    assert transcript_route.called
    assert status_route.called
    assert result_route.called
    assert error_route.called
    assert submit_route.calls.last.request.read()
    submit = submit_route.calls.last.request.content
    assert b'"genome_build":"GRCh38.p14"' in submit
    assert b'"genome_build":"GRCh38.p14"' in metadomain_route.calls.last.request.content


def test_only_two_live_build_namespaces_are_accepted_and_profiles_are_distinct() -> None:
    """The API has two known namespaces; arbitrary patch levels must fail closed."""
    assert (
        ServerSettings(metadome={"genome_build": "GRCh37.p13"}).metadome.genome_build
        == "GRCh37.p13"
    )
    with pytest.raises(ValueError):
        ServerSettings(metadome={"genome_build": "GRCh37.p12"})

    legacy = ServerSettings(metadome={"genome_build": "GRCh37.p13"})
    modern = ServerSettings(metadome={"genome_build": "GRCh38.p14"})
    legacy_client = MetaDomeClient(legacy)
    modern_client = MetaDomeClient(modern)
    assert legacy_client.data_version != modern_client.data_version
    assert legacy_client.data_versions["assembly"] == "GRCh37.p13"
    assert legacy_client.data_versions == {
        "assembly": "GRCh37.p13",
        "gencode": "v19",
        "uniprot": "2025_01",
        "gnomad": "r2.0.2",
        "clinvar": "2025-10-06",
        "pfam": "37.4",
        "metadome_app": "2.0",
        "data_doi": "10.5281/zenodo.19376150",
    }
    assert modern_client.data_versions["assembly"] == "GRCh38.p14"


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/get_transcripts/GRCh38.p14/TP53", {"gene_name": "TP53"}, "transcript_ids"),
        ("/status/GRCh38.p14/ENST00000269305.9", {}, "status"),
        ("/result/GRCh38.p14/ENST00000269305.9", {"gene_name": "TP53"}, "positional_annotation"),
    ],
)
async def test_malformed_v2_payloads_raise_typed_schema_errors(
    path: str, payload: dict[str, object], field: str
) -> None:
    """Missing required upstream fields never become empty/not-found states."""
    client = MetaDomeClient()
    with respx.mock(base_url=V2_BASE) as router:
        router.get(path).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(UpstreamUnavailableError) as exc_info:
            if field == "transcript_ids":
                await client.get_transcripts("TP53")
            elif field == "status":
                await client.get_status(TID)
            else:
                await client.get_result(TID)
    assert exc_info.value.error_code == "upstream_unavailable"
    assert exc_info.value.extra.get("field") == field
    assert exc_info.value.retryable is False
    await client.aclose()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("aa_length", "393"),
        ("has_protein_data", 1),
        ("mane_transcript_type", None),
        ("refseq_nm_numbers", ["NM_000546.6"]),
        ("gencode_id", "ENST00000269305"),
    ],
)
@respx.mock
async def test_transcript_nested_type_drift_is_typed_upstream_error(
    field: str, value: object
) -> None:
    """A malformed transcript entry never becomes a partially normalized record."""
    entry: dict[str, object] = {
        "aa_length": 393,
        "gencode_id": TID,
        "has_protein_data": True,
        "mane_transcript_type": "MANE_Select",
        "refseq_nm_numbers": "NM_000546.6",
    }
    entry[field] = value
    respx.get(f"{V2_BASE}/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(200, json={"transcript_ids": [entry]})
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_transcripts("TP53")
    assert exc_info.value.extra["field"] == f"transcript_ids[0].{field}"
    assert exc_info.value.retryable is False
    await client.aclose()


@pytest.mark.parametrize(
    "field_value",
    [
        ("protein_pos", "35"),
        ("ref_aa", None),
        ("sw_coverage", "0.5"),
        ("sw_dn_ds", {}),
        ("sw_size", True),
        ("domains", []),
    ],
)
@respx.mock
async def test_positional_annotation_nested_type_drift_is_typed_upstream_error(
    field_value: tuple[str, object],
) -> None:
    """Every result row has a strict, typed positional schema."""
    field, value = field_value
    row: dict[str, object] = {
        "cdna_pos": "c.103-105",
        "chr": "chr17",
        "chr_positions": "g.7579582-7579584",
        "domains": {},
        "protein_pos": 35,
        "ref_aa": "L",
        "ref_aa_triplet": "Leu",
        "ref_codon": "CTG",
        "strand": "-",
        "sw_coverage": 0.7,
        "sw_dn_ds": 0.4,
        "sw_size": 10,
    }
    row[field] = value
    respx.get(f"{V2_BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"positional_annotation": [row]})
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_result(TID)
    assert exc_info.value.extra["field"] == f"positional_annotation[0].{field}"
    assert exc_info.value.retryable is False
    await client.aclose()


@respx.mock
async def test_empty_object_position_is_not_accepted_as_a_result_row() -> None:
    """A non-empty result list with an empty object is not a valid landscape."""
    respx.get(f"{V2_BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"positional_annotation": [{}]})
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_result(TID)
    assert exc_info.value.extra["field"] == "positional_annotation[0].cdna_pos"
    await client.aclose()


async def test_alternate_profile_flows_into_capabilities_and_envelope(tmp_path: object) -> None:
    """A GRCh37 runtime cannot advertise the default GRCh38 provenance."""
    settings = ServerSettings(metadome={"genome_build": "GRCh37.p13"})
    client = MetaDomeClient(settings)
    cache = ResultCache(db_path=str(tmp_path) + "/cache.sqlite", data_version=client.data_version)
    service = MetaDomeService(client, cache, settings=settings)
    set_metadome_service(service)
    try:
        caps = build_capabilities()
        assert caps["genome_build"] == "GRCh37.p13"
        assert caps["data_versions"]["assembly"] == "GRCh37.p13"
        result = await run_mcp_tool("probe", lambda: _plain_payload())
        assert result["_meta"]["data_versions"]["assembly"] == "GRCh37.p13"
        cache.put_result(
            TID,
            {
                "transcript_id": TID,
                "positional_annotation": [
                    {
                        "cdna_pos": "c.1-3",
                        "chr": "chr17",
                        "chr_positions": "g.1-3",
                        "domains": {},
                        "protein_pos": 1,
                        "ref_aa": "M",
                        "ref_aa_triplet": "Met",
                        "ref_codon": "ATG",
                        "strand": "-",
                        "sw_coverage": 0.5,
                        "sw_dn_ds": 0.4,
                        "sw_size": 10,
                    }
                ],
            },
        )
        comparison = await service.compare_positions(TID, [1], response_mode="compact")
        assert "GRCh37.p13" in comparison["data_currency_caveat"]
        assert "2018-06-03" not in comparison["data_currency_caveat"]
        assert unknown_tool_envelope()["_meta"]["data_versions"]["assembly"] == "GRCh37.p13"
    finally:
        set_metadome_service(None)
        cache.close()
        await client.aclose()


async def _plain_payload() -> dict[str, object]:
    return {"answer": "ok"}
