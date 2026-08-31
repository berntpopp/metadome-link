"""Tests for the async MetaDome API client (all upstream calls mocked via respx).

Covers all six endpoints plus the three quirks the client must normalize:
the ``transcript_ids`` typo + refseq split, unknown-gene -> ``[]`` (not 404),
submit 400 -> :class:`InvalidInputError`, ``clinvar_ID`` -> ``str`` in both the
result and metadomain payloads, and the three ``poll_until_ready`` outcomes.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import time
from typing import Any

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.api.models import validate_metadomain_blocks, validate_positional_annotations
from metadome_link.config import ServerSettings
from metadome_link.exceptions import (
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UpstreamUnavailableError,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "metadome"
BASE = "https://www.metadome.app/metadome/api"
TID = "ENST00000269305.9"


def _load(name: str) -> Any:
    """Load a captured JSON fixture by file name."""
    return json.loads((FX / name).read_text())


def _fast_client() -> MetaDomeClient:
    """A client with poll intervals collapsed so deadline tests run instantly."""
    settings = ServerSettings()
    settings.metadome.poll_initial_interval_s = 0.001
    settings.metadome.poll_max_interval_s = 0.002
    return MetaDomeClient(settings)


# -- endpoint 1: get_transcripts ------------------------------------------------


@respx.mock
async def test_get_transcripts_parses_v2_key_and_splits_refseq() -> None:
    """Reads the v2 ``transcript_ids`` key and splits refseq into a list."""
    respx.get(f"{BASE}/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(200, json=_load("get_transcripts_TP53.json"))
    )
    client = MetaDomeClient()
    out = await client.get_transcripts("TP53")

    assert any(
        t["gencode_id"] == TID and t["has_protein_data"] and t["aa_length"] == 393 for t in out
    )
    canonical = next(t for t in out if t["gencode_id"] == TID)
    assert isinstance(canonical["refseq_ids"], list)
    assert canonical["refseq_ids"][0] == "NM_000546.6"
    assert len(canonical["refseq_ids"]) == 1
    assert canonical["mane_transcript_type"] == "MANE_Select"
    no_refseq = next(t for t in out if t["gencode_id"] == "ENST00000509690.6")
    assert no_refseq["refseq_ids"] == []
    await client.aclose()


@respx.mock
async def test_unknown_gene_returns_empty_list() -> None:
    """Unknown gene is HTTP 200 with an empty list -> [] (does not raise)."""
    respx.get(f"{BASE}/get_transcripts/GRCh38.p14/NOSUCHGENE").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": "No transcripts...",
                "genome_build": "GRCh38.p14",
                "transcript_ids": [],
            },
        )
    )
    client = MetaDomeClient()
    assert await client.get_transcripts("NOSUCHGENE") == []
    await client.aclose()


@respx.mock
async def test_get_transcripts_url_encodes_gene_metacharacters() -> None:
    """A gene segment with metacharacters is URL-encoded so it cannot rewrite the path."""
    route = respx.get(url__regex=rf"^{re.escape(BASE)}/get_transcripts/GRCh38.p14/.*$").mock(
        return_value=httpx.Response(200, json={"genome_build": "GRCh38.p14", "transcript_ids": []})
    )
    client = MetaDomeClient()
    await client.get_transcripts("../status/x?y=z")
    await client.aclose()

    assert route.called
    raw_path = route.calls.last.request.url.raw_path.decode()
    # The gene is a single percent-encoded path segment under /get_transcripts/GRCh38.p14/;
    # it never escapes into a new segment or a query string.
    assert raw_path == "/metadome/api/get_transcripts/GRCh38.p14/..%2Fstatus%2Fx%3Fy%3Dz"
    assert "%2F" in raw_path  # '/' -> %2F (path traversal neutralised)
    assert "%3F" in raw_path  # '?' -> %3F (query injection neutralised)
    assert "?" not in raw_path  # no real query string was introduced


# -- endpoint 2: submit_visualization -------------------------------------------


@respx.mock
async def test_submit_visualization_echoes_id() -> None:
    """A 200 submit echoes the transcript id back."""
    route = respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    client = MetaDomeClient()
    assert await client.submit_visualization(TID) == TID
    assert route.called
    # Trailing slash + JSON content type are honoured.
    sent = route.calls.last.request
    assert sent.url.path.endswith("/submit_visualization/")
    assert sent.headers["content-type"].startswith("application/json")
    assert json.loads(sent.content) == {
        "transcript_id": TID,
        "genome_build": "GRCh38.p14",
    }
    await client.aclose()


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"transcript_id": "ENST00000504937.5", "genome_build": "GRCh38.p14"},
        {"transcript_id": TID, "genome_build": "GRCh37.p13"},
    ],
)
@respx.mock
async def test_submit_visualization_requires_authoritative_echo(response: dict[str, str]) -> None:
    """A submit response must echo both the requested id and configured build."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json=response)
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.submit_visualization(TID)
    assert exc_info.value.extra["field"] in {"transcript_id", "genome_build"}
    await client.aclose()


@respx.mock
async def test_submit_visualization_allows_documented_absent_build_echo() -> None:
    """The confirmed-live response echoes only transcript_id; build is optional."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID})
    )
    client = MetaDomeClient()
    assert await client.submit_visualization(TID) == TID
    await client.aclose()


@pytest.mark.parametrize("method", ["get_status", "get_result", "get_error"])
async def test_direct_transcript_endpoints_reject_path_rewriting(method: str) -> None:
    """Direct client calls validate transcript IDs before interpolating URL paths."""
    client = MetaDomeClient()
    with pytest.raises(InvalidInputError):
        await getattr(client, method)("../status/GRCh38.p14/ENST00000269305.9")
    await client.aclose()


@respx.mock
async def test_submit_visualization_400_raises_invalid_input() -> None:
    """A 400 from upstream maps to InvalidInputError."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(
            400, json={"error": "not a valid transcript id: ENST00000269305.9"}
        )
    )
    client = MetaDomeClient()
    with pytest.raises(InvalidInputError):
        await client.submit_visualization(TID)
    await client.aclose()


async def test_submit_visualization_unversioned_id_raises_before_request() -> None:
    """An unversioned id is rejected locally by validate_transcript_id."""
    client = MetaDomeClient()
    with pytest.raises(InvalidInputError) as ei:
        await client.submit_visualization("ENST00000269305")
    assert ei.value.extra.get("field") == "transcript_id"
    await client.aclose()


# -- endpoint 3: status ---------------------------------------------------------


@respx.mock
async def test_get_status_passthrough() -> None:
    """get_status returns the raw status string verbatim."""
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )
    client = MetaDomeClient()
    assert await client.get_status(TID) == "SUCCESS"
    await client.aclose()


# -- endpoint 4: result ---------------------------------------------------------


@respx.mock
async def test_get_result_coerces_clinvar_id_to_str() -> None:
    """Every positional ClinVar clinvar_ID is a str after normalization."""
    respx.get(f"{BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json=_load("result_TP53.json"))
    )
    client = MetaDomeClient()
    result = await client.get_result(TID)

    assert result["transcript_id"] == TID
    assert result["gene_name"] == "TP53"
    by_pos = {e["protein_pos"]: e for e in result["positional_annotation"]}
    p35 = by_pos[35]
    assert isinstance(p35["ClinVar"][0]["clinvar_ID"], str)
    assert p35["ClinVar"][0]["clinvar_ID"] == "12371"
    # p.175 carries both a ClinVar entry and a meta-domain mapping.
    p175 = by_pos[175]
    assert isinstance(p175["ClinVar"][0]["clinvar_ID"], str)
    assert p175["domains"]["PF00870"]["consensus_pos"] == [81]
    await client.aclose()


@respx.mock
async def test_get_result_404_raises_not_found() -> None:
    """A 404 (result not built yet) maps to NotFoundError."""
    respx.get(f"{BASE}/result/GRCh38.p14/{TID}").mock(return_value=httpx.Response(404))
    client = MetaDomeClient()
    with pytest.raises(NotFoundError):
        await client.get_result(TID)
    await client.aclose()


# -- endpoint 5: error ----------------------------------------------------------


@respx.mock
async def test_get_error_returns_dict() -> None:
    """get_error returns the stored error dict."""
    respx.get(f"{BASE}/error/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(
            200, json={"error": "error running visualization job", "stacktrace": "..."}
        )
    )
    client = MetaDomeClient()
    err = await client.get_error(TID)
    assert err["error"] == "error running visualization job"
    await client.aclose()


# -- endpoint 6: get_metadomain_annotation --------------------------------------


@respx.mock
async def test_get_metadomain_annotation_coerces_clinvar_id() -> None:
    """The metadomain payload's float clinvar_ID is coerced to a str."""
    route = respx.post(f"{BASE}/get_metadomain_annotation/").mock(
        return_value=httpx.Response(200, json=_load("metadomain_p175.json"))
    )
    client = MetaDomeClient()
    out = await client.get_metadomain_annotation(TID, 175, {"PF00870": [81]})

    patho = out["PF00870"]["pathogenic_variants"]
    assert patho, "fixture should have pathogenic variants"
    for variant in patho:
        assert isinstance(variant["clinvar_ID"], str)
    # 6527.0 (float) -> "6527" (no trailing .0).
    assert patho[0]["clinvar_ID"] == "6527"
    # request shape: trailing slash + all four required keys.
    sent = route.calls.last.request
    assert sent.url.path.endswith("/get_metadomain_annotation/")
    body = json.loads(sent.content)
    assert body == {
        "transcript_id": TID,
        "genome_build": "GRCh38.p14",
        "protein_position": 175,
        "requested_domains": {"PF00870": [81]},
    }
    await client.aclose()


@respx.mock
async def test_live_v2_nested_variant_fields_are_supported() -> None:
    """Live endpoint-6 and result records retain their discriminating fields."""
    metadomain = _load("metadomain_p175.json")
    for variant in metadomain["PF00870"]["normal_variants"]:
        variant["exon_numbers"] = "5, 5, 5"
    for variant in metadomain["PF00870"]["pathogenic_variants"]:
        variant["exon_numbers"] = "1, 1, 1"
        variant["clinvar_clinsig"] = "Pathogenic"
    respx.post(f"{BASE}/get_metadomain_annotation/").mock(
        return_value=httpx.Response(200, json=metadomain)
    )
    result = _load("result_TP53.json")
    for row in result["positional_annotation"]:
        for variant in row.get("ClinVar", []):
            variant["clinvar_clinsig"] = "Pathogenic"
    respx.get(f"{BASE}/result/GRCh38.p14/{TID}").mock(return_value=httpx.Response(200, json=result))
    client = MetaDomeClient()
    out = await client.get_metadomain_annotation(TID, 175, {"PF00870": [81]})
    assert out["PF00870"]["normal_variants"][0]["exon_numbers"] == "5, 5, 5"
    landscape = await client.get_result(TID)
    assert any(
        variant["clinvar_clinsig"] == "Pathogenic"
        for row in landscape["positional_annotation"]
        for variant in row.get("ClinVar", [])
    )
    await client.aclose()


def test_huge_numeric_values_fail_as_typed_schema_errors() -> None:
    """Arbitrarily large JSON integers cannot escape validators as OverflowError."""
    metadomain = _load("metadomain_p175.json")
    metadomain["PF00870"]["normal_variants"][0]["allele_count"] = 10**1000
    with pytest.raises(UpstreamUnavailableError):
        validate_metadomain_blocks(metadomain)

    result = _load("result_TP53.json")
    result["positional_annotation"][0]["sw_coverage"] = 10**1000
    with pytest.raises(UpstreamUnavailableError):
        validate_positional_annotations(result["positional_annotation"])


# -- poll_until_ready: three outcomes -------------------------------------------


@respx.mock
async def test_poll_ready_immediate_success() -> None:
    """SUCCESS on the first status check -> ('ready', result_dict)."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )
    respx.get(f"{BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json=_load("result_TP53.json"))
    )
    client = _fast_client()
    state, result = await client.poll_until_ready(TID, soft_deadline_s=5.0)
    assert state == "ready"
    assert result is not None
    assert result["transcript_id"] == TID
    await client.aclose()


@respx.mock
async def test_poll_pending_then_success() -> None:
    """PENDING then SUCCESS within the deadline -> ('ready', result_dict)."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    statuses = iter(["PENDING", "STARTED", "SUCCESS"])
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        side_effect=lambda request: httpx.Response(200, json={"status": next(statuses)})
    )
    respx.get(f"{BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json=_load("result_TP53.json"))
    )
    client = _fast_client()
    state, result = await client.poll_until_ready(TID, soft_deadline_s=5.0)
    assert state == "ready"
    assert result is not None
    await client.aclose()


@respx.mock
async def test_poll_failure_returns_error_dict() -> None:
    """FAILURE -> ('failed', error_dict)."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    respx.get(f"{BASE}/error/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(
            200, json={"error": "error running visualization job", "stacktrace": "..."}
        )
    )
    client = _fast_client()
    state, err = await client.poll_until_ready(TID, soft_deadline_s=5.0)
    assert state == "failed"
    assert err is not None
    assert err["error"] == "error running visualization job"
    await client.aclose()


@respx.mock
async def test_poll_processing_at_deadline() -> None:
    """Still PENDING when the soft deadline elapses -> ('processing', None)."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    client = MetaDomeClient()
    state, result = await client.poll_until_ready(TID, soft_deadline_s=0.05)
    assert state == "processing"
    assert result is None
    await client.aclose()


@respx.mock
async def test_poll_status_call_is_bounded_by_soft_deadline() -> None:
    """A hanging status request cannot outlive the polling soft deadline."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    client = MetaDomeClient()

    async def hanging_status(_: str) -> str:
        await asyncio.sleep(0.1)
        return "PENDING"

    client.get_status = hanging_status  # type: ignore[method-assign]
    started = time.monotonic()
    state, result = await client.poll_until_ready(TID, soft_deadline_s=0.01)
    assert time.monotonic() - started < 0.05
    assert state == "processing"
    assert result is None
    await client.aclose()


# -- reliability layer ----------------------------------------------------------


@respx.mock
async def test_429_after_retries_raises_rate_limited() -> None:
    """A persistent 429 (after retries) maps to RateLimitedError."""
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(return_value=httpx.Response(429))
    settings = ServerSettings()
    settings.metadome.max_retries = 1
    client = MetaDomeClient(settings)
    with pytest.raises(RateLimitedError):
        await client.get_status(TID)
    await client.aclose()


@respx.mock
async def test_5xx_after_retries_raises_upstream_unavailable() -> None:
    """A persistent 503 (after retries) maps to UpstreamUnavailableError."""
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(return_value=httpx.Response(503))
    settings = ServerSettings()
    settings.metadome.max_retries = 1
    client = MetaDomeClient(settings)
    with pytest.raises(UpstreamUnavailableError):
        await client.get_status(TID)
    await client.aclose()


@respx.mock
async def test_timeout_raises_upstream_unavailable() -> None:
    """A connect timeout (after retries) maps to UpstreamUnavailableError."""
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(side_effect=httpx.ConnectTimeout("boom"))
    settings = ServerSettings()
    settings.metadome.max_retries = 0
    client = MetaDomeClient(settings)
    with pytest.raises(UpstreamUnavailableError):
        await client.get_status(TID)
    await client.aclose()


async def test_injected_client_not_closed_by_aclose() -> None:
    """An injected httpx.AsyncClient is reused as-is and not owned by the client."""
    injected = httpx.AsyncClient()
    client = MetaDomeClient(client=injected)
    await client.aclose()
    assert not injected.is_closed
    await injected.aclose()
