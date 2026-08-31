"""MetaDome v2 live-API and provenance contract.

Captured against the public MetaDome 2.0 service and its Zenodo record on
2026-08-31.  The build token is part of every upstream operation: omitting the
``.p14`` suffix returns a plausible HTTP-200 empty transcript list.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.config import ServerSettings
from metadome_link.constants import DATA_VERSIONS, METADOME_DATA_VERSION
from metadome_link.exceptions import UpstreamUnavailableError

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
        (
            "/result/GRCh38.p14/ENST00000269305.9",
            {"transcript_id": TID, "gene_name": "TP53"},
            "positional_annotation",
        ),
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
        return_value=httpx.Response(
            200, json={"genome_build": "GRCh38.p14", "transcript_ids": [entry]}
        )
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
        return_value=httpx.Response(
            200, json={"transcript_id": TID, "positional_annotation": [row]}
        )
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
        return_value=httpx.Response(200, json={"transcript_id": TID, "positional_annotation": [{}]})
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_result(TID)
    assert exc_info.value.extra["field"] == "positional_annotation[0].cdna_pos"
    await client.aclose()


def _valid_position() -> dict[str, object]:
    """Return one valid result row for schema-adversarial payload tests."""
    return {
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


def _valid_metadomain() -> dict[str, object]:
    """Return one valid endpoint-6 block with both variant list shapes."""
    common = {
        "alt": "A",
        "alt_aa": "H",
        "alt_aa_triplet": "His",
        "alt_codon": "CAC",
        "cdna_pos": "c.1-3",
        "chr": "chr1",
        "chr_positions": "g.1-3",
        "gene_name": "TP73",
        "pos": 1,
        "protein_pos": 1,
        "ref": "G",
        "ref_aa": "R",
        "ref_aa_triplet": "Arg",
        "ref_codon": "CGC",
        "strand": "+",
        "type": "missense",
    }
    normal = {**common, "allele_count": 1.0, "allele_number": 245218.0}
    pathogenic = {**common, "clinvar_ID": 6527.0}
    return {
        "PF00870": {
            "alignment_depth": 1,
            "normal_variants": [normal],
            "pathogenic_variants": [pathogenic],
        }
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda block: block["PF00870"].update({"pathogenic_variants": [{}]}),
        lambda block: block["PF00870"].update({"pathogenic_variants": {}}),
        lambda block: block["PF00870"].update({"normal_variants": "bad"}),
        lambda block: block["PF00870"].update({"alignment_depth": []}),
        lambda block: block["PF00870"]["pathogenic_variants"][0].update({"clinvar_ID": "bad"}),
        lambda block: block["PF00870"]["normal_variants"][0].update({"gene_name": None}),
        lambda block: block["PF00870"]["normal_variants"][0].update({"protein_pos": "1"}),
        lambda block: block["PF00870"]["pathogenic_variants"][0].update({"alt": None}),
        lambda block: block["PF00870"]["normal_variants"][0].update({"unexpected": 1}),
    ],
    ids=[
        "empty-pathogenic",
        "dict-pathogenic",
        "string-normal",
        "list-depth",
        "bad-clinvar",
        "bad-gene-name",
        "bad-protein-pos",
        "bad-alt",
        "unexpected-field",
    ],
)
@respx.mock
async def test_metadomain_nested_schema_drift_is_typed_upstream_error(mutate: object) -> None:
    """Endpoint 6 blocks and variants are validated before shaping or coercion."""
    payload = _valid_metadomain()
    assert callable(mutate)
    mutate(payload)
    respx.post(f"{V2_BASE}/get_metadomain_annotation/").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_metadomain_annotation(TID, 1, {"PF00870": [1]})
    assert exc_info.value.extra["field"].startswith("PF00870")
    assert exc_info.value.retryable is False
    await client.aclose()


@pytest.mark.parametrize("consensus", [None, "bad", [], [1, "bad"], [0], [None]])
@respx.mock
async def test_nested_position_domain_schema_drift_is_typed_upstream_error(
    consensus: object,
) -> None:
    """Domain memberships reject invalid, empty, null-containing position lists."""
    row = _valid_position()
    row["domains"] = {
        "PF00870": {
            "consensus_pos": consensus,
            "normal_variant_count": 0,
            "normal_missense_variant_count": 0,
            "pathogenic_variant_count": 0,
            "pathogenic_missense_variant_count": 0,
        }
    }
    respx.get(f"{V2_BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(
            200, json={"transcript_id": TID, "positional_annotation": [row]}
        )
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_result(TID)
    assert exc_info.value.extra["field"] == "positional_annotation[0].domains.PF00870.consensus_pos"
    await client.aclose()


@pytest.mark.parametrize(
    "payload", [{"transcript_ids": []}, {"genome_build": "GRCh37.p13", "transcript_ids": []}]
)
@respx.mock
async def test_transcript_response_requires_exact_echoed_build(payload: dict[str, object]) -> None:
    """Missing or mismatched build echoes cannot be mistaken for a valid response."""
    respx.get(f"{V2_BASE}/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_transcripts("TP53")
    assert exc_info.value.extra["field"] == "genome_build"
    await client.aclose()


@pytest.mark.parametrize("echo", [None, "ENST00000504937.5"])
@respx.mock
async def test_result_response_requires_requested_transcript_echo(echo: str | None) -> None:
    """A result for another or unspecified transcript must never enter the cache."""
    body: dict[str, object] = {"positional_annotation": [_valid_position()]}
    if echo is not None:
        body["transcript_id"] = echo
    respx.get(f"{V2_BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json=body)
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_result(TID)
    assert exc_info.value.extra["field"] == "transcript_id"
    await client.aclose()


@pytest.mark.parametrize("field", ["sw_coverage", "sw_dn_ds"])
@respx.mock
async def test_nonfinite_result_numbers_are_rejected(field: str) -> None:
    """NaN and infinity cannot pass through numeric upstream validation."""
    row = _valid_position()
    row[field] = float("nan")
    respx.get(f"{V2_BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(
            200,
            content=json.dumps(
                {"transcript_id": TID, "positional_annotation": [row]}, allow_nan=True
            ).encode(),
            headers={"content-type": "application/json"},
        )
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError):
        await client.get_result(TID)
    await client.aclose()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@respx.mock
async def test_nonfinite_metadomain_numbers_are_rejected(value: float) -> None:
    """Endpoint-6 numeric fields must be finite before any normalization."""
    payload = _valid_metadomain()
    payload["PF00870"]["normal_variants"][0]["allele_count"] = value
    respx.post(f"{V2_BASE}/get_metadomain_annotation/").mock(
        return_value=httpx.Response(
            200,
            content=json.dumps(payload, allow_nan=True).encode(),
            headers={"content-type": "application/json"},
        )
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError):
        await client.get_metadomain_annotation(TID, 1, {"PF00870": [1]})
    await client.aclose()
