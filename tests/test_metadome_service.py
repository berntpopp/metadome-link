"""Tests for the MetaDome service orchestration layer (Task 6).

The service returns **plain dicts** (no ``success``/``_meta`` envelope — that is
the MCP plane's job) and **raises typed exceptions** on error. Every record-
derived payload carries ``recommended_citation``.

Upstream is mocked with respx through a real :class:`MetaDomeClient` (poll
intervals collapsed so deadline tests are instant); the result cache is a real
:class:`ResultCache` on a ``tmp_path`` SQLite db.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.cache.store import ResultCache
from metadome_link.config import ServerSettings
from metadome_link.exceptions import (
    DataUnavailableError,
    InvalidInputError,
    NotFoundError,
)
from metadome_link.services.landscape import (
    domains_for_position,
    intolerant_runs,
    position_to_entry,
    slice_positions,
    variant_evidence_for,
)
from metadome_link.services.metadome_service import MetaDomeService
from metadome_link.services.resolution import (
    detect_query_type,
    pick_canonical,
    sort_transcripts,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "metadome"
BASE = "https://www.metadome.app/metadome/api"
TID = "ENST00000269305.9"


def _load(name: str) -> Any:
    """Load a captured JSON fixture by file name."""
    return json.loads((FX / name).read_text())


def _fast_settings() -> ServerSettings:
    """Settings with poll intervals collapsed so deadline paths run instantly."""
    settings = ServerSettings()
    settings.metadome.poll_initial_interval_s = 0.001
    settings.metadome.poll_max_interval_s = 0.002
    settings.metadome.poll_soft_deadline_s = 5.0
    return settings


@pytest.fixture
def cache(tmp_path: pathlib.Path) -> Iterator[ResultCache]:
    """A real ResultCache on a temporary SQLite db."""
    store = ResultCache(db_path=str(tmp_path / "cache.sqlite"))
    try:
        yield store
    finally:
        store.close()


def _make_service(cache: ResultCache, settings: ServerSettings | None = None) -> MetaDomeService:
    """Build a service over a real (respx-mocked) client + the given cache."""
    cfg = settings if settings is not None else _fast_settings()
    client = MetaDomeClient(cfg)
    return MetaDomeService(client, cache, settings=cfg)


# ---------------------------------------------------------------------------
# resolution.py pure helpers
# ---------------------------------------------------------------------------


def test_sort_transcripts_orders_by_aa_length_desc() -> None:
    """sort_transcripts ranks longest protein first."""
    ts = [{"aa_length": 100}, {"aa_length": 393}, {"aa_length": 285}]
    out = sort_transcripts(ts)
    assert [t["aa_length"] for t in out] == [393, 285, 100]


def test_pick_canonical_is_first_protein_coding() -> None:
    """pick_canonical returns the longest has_protein_data=true transcript id."""
    ts = sort_transcripts(
        [
            {"gencode_id": "A", "aa_length": 393, "has_protein_data": False},
            {"gencode_id": "B", "aa_length": 346, "has_protein_data": True},
            {"gencode_id": "C", "aa_length": 393, "has_protein_data": True},
        ]
    )
    assert pick_canonical(ts) == "C"


def test_pick_canonical_prefers_analyzable_mane_select() -> None:
    """MetaDome v2's MANE Select wins over an equally long earlier entry."""
    transcripts = sort_transcripts(
        [
            {
                "gencode_id": "ENST00000503591.2",
                "aa_length": 393,
                "has_protein_data": True,
                "mane_transcript_type": "",
            },
            {
                "gencode_id": "ENST00000269305.9",
                "aa_length": 393,
                "has_protein_data": True,
                "mane_transcript_type": "MANE_Select",
            },
        ]
    )

    assert pick_canonical(transcripts) == "ENST00000269305.9"


def test_pick_canonical_none_when_no_protein_data() -> None:
    """No protein-coding transcript -> no canonical."""
    ts = [{"gencode_id": "A", "aa_length": 100, "has_protein_data": False}]
    assert pick_canonical(ts) is None


def test_detect_query_type() -> None:
    """ENST queries are 'id'; gene symbols are 'gene'."""
    assert detect_query_type("ENST00000269305.9") == "id"
    assert detect_query_type("TP53") == "gene"


# ---------------------------------------------------------------------------
# landscape.py pure helpers
# ---------------------------------------------------------------------------


def test_position_to_entry_one_based_lookup() -> None:
    """position_to_entry looks up by protein_pos (1-based), not list index."""
    landscape = _load("result_TP53.json")
    entry = position_to_entry(landscape, 175)
    assert entry["protein_pos"] == 175
    assert entry["ref_aa"] == "R"


def test_position_to_entry_out_of_range_raises() -> None:
    """A position past aa_length raises InvalidInputError."""
    landscape = _load("result_TP53.json")
    with pytest.raises(InvalidInputError):
        position_to_entry(landscape, 99999)
    with pytest.raises(InvalidInputError):
        position_to_entry(landscape, 0)


def test_slice_positions_inclusive_range() -> None:
    """slice_positions returns entries whose protein_pos is within [start, stop]."""
    landscape = _load("result_TP53.json")
    sliced = slice_positions(landscape, 173, 177)
    positions = [e["protein_pos"] for e in sliced]
    assert positions == [173, 174, 175, 176, 177]


def test_intolerant_runs_finds_constrained_region() -> None:
    """The DNA-binding stretch (low sw_dn_ds, p.173-177) is an intolerant run."""
    landscape = _load("result_TP53.json")
    runs = intolerant_runs(landscape, threshold=0.5, min_run=3, top_n=15)
    assert runs, "expected at least one intolerant run"
    # The contiguous run p.173-177 (all sw_dn_ds < 0.5) must be present.
    covered: set[int] = set()
    for run in runs:
        covered.update(range(run["start"], run["stop"] + 1))
        assert run["mean_sw_dn_ds"] < 0.5
        assert run["length"] >= 3
    assert {173, 174, 175, 176, 177} <= covered


def test_intolerant_runs_respects_top_n() -> None:
    """top_n caps the number of returned runs."""
    landscape = _load("result_TP53.json")
    runs = intolerant_runs(landscape, threshold=2.0, min_run=1, top_n=2)
    assert len(runs) <= 2


def test_domains_for_position_derives_consensus_map() -> None:
    """domains_for_position derives {PF: [consensus_pos]} from the residue."""
    landscape = _load("result_TP53.json")
    derived = domains_for_position(landscape, 175)
    assert derived == {"PF00870": [81]}


def test_domains_for_position_empty_for_non_domain_residue() -> None:
    """A residue with no domain mapping yields an empty dict."""
    landscape = _load("result_TP53.json")
    assert domains_for_position(landscape, 35) == {}


def test_variant_evidence_for_source_filter() -> None:
    """variant_evidence_for filters residue and homolog sources together."""
    landscape = _load("result_TP53.json")
    entry = position_to_entry(landscape, 175)
    both = variant_evidence_for(entry, "both")
    assert both["residue_level"]["gnomad"]["available"] is False
    assert both["residue_level"]["clinvar"]["variant_count"] == 1
    assert both["meta_domain_homolog_aggregate"]["gnomad"]["variant_count"] == 2
    gnomad_only = variant_evidence_for(entry, "gnomad")
    assert "gnomad" in gnomad_only["residue_level"]
    assert "clinvar" not in gnomad_only["residue_level"]
    clinvar_only = variant_evidence_for(entry, "clinvar")
    assert "clinvar" in clinvar_only["residue_level"]
    assert "gnomad" not in clinvar_only["residue_level"]


# ---------------------------------------------------------------------------
# resolve_transcript
# ---------------------------------------------------------------------------


@respx.mock
async def test_resolve_transcript_gene_flags_canonical(cache: ResultCache) -> None:
    """A gene query returns transcripts sorted desc with the canonical flagged."""
    respx.get(f"{BASE}/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(200, json=_load("get_transcripts_TP53.json"))
    )
    svc = _make_service(cache)
    out = await svc.resolve_transcript("TP53", response_mode="standard")
    assert out["resolved_from"] == "gene"
    assert out["gene_name"] == "TP53"
    assert out["canonical_transcript_id"] == TID
    # Sorted by aa_length descending; the analyzable MANE Select is canonical.
    lengths = [t["aa_length"] for t in out["transcripts"]]
    assert lengths == sorted(lengths, reverse=True)
    canon = next(t for t in out["transcripts"] if t["gencode_id"] == TID)
    assert canon["canonical"] is True
    assert "recommended_citation" in out
    await svc.aclose()


@respx.mock
async def test_resolve_transcript_id_passthrough(cache: ResultCache) -> None:
    """A bare ENST id is validated and echoed without an upstream call."""
    svc = _make_service(cache)
    out = await svc.resolve_transcript(TID, response_mode="compact")
    assert out["resolved_from"] == "id"
    assert out["transcript_id"] == TID
    assert "recommended_citation" in out
    await svc.aclose()


@respx.mock
async def test_resolve_transcript_unknown_gene_raises_not_found(cache: ResultCache) -> None:
    """An unknown gene (empty upstream list) raises NotFoundError."""
    respx.get(f"{BASE}/get_transcripts/GRCh38.p14/NOSUCHGENE").mock(
        return_value=httpx.Response(
            200, json={"message": "none", "genome_build": "GRCh38.p14", "transcript_ids": []}
        )
    )
    svc = _make_service(cache)
    with pytest.raises(NotFoundError):
        await svc.resolve_transcript("NOSUCHGENE", response_mode="compact")
    await svc.aclose()


# ---------------------------------------------------------------------------
# request_landscape
# ---------------------------------------------------------------------------


@respx.mock
async def test_request_landscape_ready(cache: ResultCache) -> None:
    """SUCCESS status -> status 'ready'."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )
    svc = _make_service(cache)
    out = await svc.request_landscape(TID, response_mode="compact")
    assert out["status"] == "ready"
    assert out["job_id"] == TID
    assert out["transcript_id"] == TID
    await svc.aclose()


@respx.mock
async def test_request_landscape_processing(cache: ResultCache) -> None:
    """A still-building status -> status 'processing' with poll hints."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    svc = _make_service(cache)
    out = await svc.request_landscape(TID, response_mode="compact")
    assert out["status"] == "processing"
    assert out["poll_after_s"] > 0
    assert "cold_build_warning" in out
    await svc.aclose()


@respx.mock
async def test_request_landscape_failure_is_non_retryable(cache: ResultCache) -> None:
    """A generic build FAILURE is a NON-retryable DataUnavailableError (no retry loop).

    A MetaDome FAILURE is a completed-and-crashed job whose error is cached
    upstream; re-submitting never clears it, so it must not be reported as a
    retryable transient error (the bug that caused endless BRCA2 retries).
    """
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    respx.get(f"{BASE}/error/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"error": "boom", "stacktrace": "some other crash"})
    )
    svc = _make_service(cache)
    with pytest.raises(DataUnavailableError) as ei:
        await svc.request_landscape(TID, response_mode="compact")
    assert ei.value.retryable is False
    await svc.aclose()


@respx.mock
async def test_request_landscape_no_protein_data_is_invalid_input(cache: ResultCache) -> None:
    """A FAILURE whose stacktrace is the no-protein-data crash maps to invalid_input.

    This is the real BRCA2 case: has_protein_data=false transcripts crash the
    MetaDome builder on ``_protein.id``; we surface a non-retryable invalid_input
    telling the caller to pick a protein-coding transcript.
    """
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    respx.get(f"{BASE}/error/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": "error running visualization job",
                "stacktrace": "...\n    self.protein_id = _protein.id\n"
                "AttributeError: 'NoneType' object has no attribute 'id'\n",
            },
        )
    )
    svc = _make_service(cache)
    with pytest.raises(InvalidInputError) as ei:
        await svc.request_landscape(TID, response_mode="compact")
    assert ei.value.error_code == "invalid_input"
    assert ei.value.retryable is False
    assert ei.value.extra.get("field") == "transcript_id"
    await svc.aclose()


# ---------------------------------------------------------------------------
# get_landscape
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_landscape_processing_path(cache: ResultCache) -> None:
    """On a cache miss with a still-building job, returns status 'processing'."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    settings = _fast_settings()
    settings.metadome.poll_soft_deadline_s = 0.05
    svc = _make_service(cache, settings)
    out = await svc.get_landscape(TID, limit=200, offset=0, response_mode="compact")
    assert out["success"] is True
    assert out["status"] == "processing"
    assert out["transcript_id"] == TID
    assert out["poll_after_s"] > 0
    await svc.aclose()


@respx.mock
async def test_get_landscape_ready_caches_and_paginates(cache: ResultCache) -> None:
    """A ready job is fetched, cached, and the positions paginated."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    status_route = respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )
    result_route = respx.get(f"{BASE}/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json=_load("result_TP53.json"))
    )
    svc = _make_service(cache)
    out = await svc.get_landscape(TID, limit=5, offset=0, response_mode="standard")
    assert out["transcript_id"] == TID
    assert out["gene_name"] == "TP53"
    assert out["domains"]
    assert out["pagination"]["limit"] == 5
    assert out["pagination"]["returned"] == 5
    assert out["pagination"]["total"] == 20
    assert out["pagination"]["truncated"] is True
    assert len(out["positional_annotation"]) == 5
    assert "recommended_citation" in out

    # Second call hits the cache: no new status/result upstream calls.
    status_calls = status_route.call_count
    result_calls = result_route.call_count
    out2 = await svc.get_landscape(TID, limit=5, offset=0, response_mode="standard")
    assert out2["transcript_id"] == TID
    assert status_route.call_count == status_calls
    assert result_route.call_count == result_calls
    await svc.aclose()


@respx.mock
async def test_get_landscape_slices_by_position_range(cache: ResultCache) -> None:
    """position_start/stop slice the landscape instead of paginating."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.get_landscape(
        TID,
        position_start=173,
        position_stop=177,
        limit=200,
        offset=0,
        response_mode="standard",
    )
    positions = [e["protein_pos"] for e in out["positional_annotation"]]
    assert positions == [173, 174, 175, 176, 177]
    await svc.aclose()


@respx.mock
async def test_get_landscape_failed_is_non_retryable(cache: ResultCache) -> None:
    """A FAILURE during the poll raises a NON-retryable error (no endless retry)."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID, "genome_build": "GRCh38.p14"})
    )
    respx.get(f"{BASE}/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    respx.get(f"{BASE}/error/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"error": "boom"})
    )
    svc = _make_service(cache)
    with pytest.raises(DataUnavailableError) as ei:
        await svc.get_landscape(TID, limit=200, offset=0, response_mode="compact")
    assert ei.value.retryable is False
    await svc.aclose()


@respx.mock
async def test_resolve_transcript_not_analyzable_when_no_protein_data(cache: ResultCache) -> None:
    """A gene whose transcripts all lack protein data is flagged not analyzable (BRCA2)."""
    respx.get(f"{BASE}/get_transcripts/GRCh38.p14/BRCA2").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": "Retrieved transcripts for gene 'BRCA2'",
                "genome_build": "GRCh38.p14",
                "transcript_ids": [
                    {
                        "aa_length": 3418,
                        "gencode_id": "ENST00000380152.3",
                        "has_protein_data": False,
                        "mane_transcript_type": "",
                        "refseq_nm_numbers": "",
                    },
                    {
                        "aa_length": 3418,
                        "gencode_id": "ENST00000544455.1",
                        "has_protein_data": False,
                        "mane_transcript_type": "",
                        "refseq_nm_numbers": "NM_000059.3",
                    },
                ],
            },
        )
    )
    svc = _make_service(cache)
    out = await svc.resolve_transcript("BRCA2", response_mode="standard")
    assert out["analyzable"] is False
    assert out["canonical_transcript_id"] is None
    assert "has_protein_data=false" in out["note"]
    await svc.aclose()
