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
    InvalidInputError,
    NotFoundError,
    UpstreamUnavailableError,
)
from metadome_link.services.landscape import (
    domains_for_position,
    intolerant_runs,
    position_to_entry,
    slice_positions,
    variant_counts_for,
)
from metadome_link.services.metadome_service import MetaDomeService
from metadome_link.services.resolution import (
    detect_query_type,
    pick_canonical,
    sort_transcripts,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "metadome"
BASE = "https://stuart.radboudumc.nl/metadome/api"
TID = "ENST00000269305.4"


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


def test_pick_canonical_none_when_no_protein_data() -> None:
    """No protein-coding transcript -> no canonical."""
    ts = [{"gencode_id": "A", "aa_length": 100, "has_protein_data": False}]
    assert pick_canonical(ts) is None


def test_detect_query_type() -> None:
    """ENST queries are 'id'; gene symbols are 'gene'."""
    assert detect_query_type("ENST00000269305.4") == "id"
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


def test_variant_counts_for_source_filter() -> None:
    """variant_counts_for filters by source."""
    landscape = _load("result_TP53.json")
    entry = position_to_entry(landscape, 175)
    both = variant_counts_for(entry, "both")
    assert both["gnomad"]["variant_count"] == 2
    assert both["clinvar"]["variant_count"] == 2
    gnomad_only = variant_counts_for(entry, "gnomad")
    assert "gnomad" in gnomad_only and "clinvar" not in gnomad_only
    clinvar_only = variant_counts_for(entry, "clinvar")
    assert "clinvar" in clinvar_only and "gnomad" not in clinvar_only


# ---------------------------------------------------------------------------
# resolve_transcript
# ---------------------------------------------------------------------------


@respx.mock
async def test_resolve_transcript_gene_flags_canonical(cache: ResultCache) -> None:
    """A gene query returns transcripts sorted desc with the canonical flagged."""
    respx.get(f"{BASE}/get_transcripts/TP53").mock(
        return_value=httpx.Response(200, json=_load("get_transcripts_TP53.json"))
    )
    svc = _make_service(cache)
    out = await svc.resolve_transcript("TP53", response_mode="standard")
    assert out["resolved_from"] == "gene"
    assert out["gene_name"] == "TP53"
    assert out["canonical_transcript_id"] == TID
    # Sorted by aa_length descending; first protein-coding 393 is canonical.
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
    respx.get(f"{BASE}/get_transcripts/NOSUCHGENE").mock(
        return_value=httpx.Response(200, json={"message": "none", "trancript_ids": []})
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
        return_value=httpx.Response(200, json={"transcript_id": TID})
    )
    respx.get(f"{BASE}/status/{TID}/").mock(
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
        return_value=httpx.Response(200, json={"transcript_id": TID})
    )
    respx.get(f"{BASE}/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    svc = _make_service(cache)
    out = await svc.request_landscape(TID, response_mode="compact")
    assert out["status"] == "processing"
    assert out["poll_after_s"] > 0
    assert "cold_build_warning" in out
    await svc.aclose()


@respx.mock
async def test_request_landscape_failure_raises_upstream(cache: ResultCache) -> None:
    """A FAILURE status raises UpstreamUnavailableError with the error summary."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID})
    )
    respx.get(f"{BASE}/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    respx.get(f"{BASE}/error/{TID}/").mock(
        return_value=httpx.Response(200, json={"error": "boom", "stacktrace": "..."})
    )
    svc = _make_service(cache)
    with pytest.raises(UpstreamUnavailableError):
        await svc.request_landscape(TID, response_mode="compact")
    await svc.aclose()


# ---------------------------------------------------------------------------
# get_landscape
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_landscape_processing_path(cache: ResultCache) -> None:
    """On a cache miss with a still-building job, returns status 'processing'."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID})
    )
    respx.get(f"{BASE}/status/{TID}/").mock(
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
        return_value=httpx.Response(200, json={"transcript_id": TID})
    )
    status_route = respx.get(f"{BASE}/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )
    result_route = respx.get(f"{BASE}/result/{TID}/").mock(
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
async def test_get_landscape_failed_raises_upstream(cache: ResultCache) -> None:
    """A FAILURE during the poll raises UpstreamUnavailableError."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID})
    )
    respx.get(f"{BASE}/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    respx.get(f"{BASE}/error/{TID}/").mock(
        return_value=httpx.Response(200, json={"error": "boom"})
    )
    svc = _make_service(cache)
    with pytest.raises(UpstreamUnavailableError):
        await svc.get_landscape(TID, limit=200, offset=0, response_mode="compact")
    await svc.aclose()


# ---------------------------------------------------------------------------
# _require_landscape (via the position tools) and not-ready path
# ---------------------------------------------------------------------------


@respx.mock
async def test_require_landscape_not_ready_raises_not_found(cache: ResultCache) -> None:
    """A position tool on a not-yet-built landscape raises not_found/switch_tool."""
    respx.post(f"{BASE}/submit_visualization/").mock(
        return_value=httpx.Response(200, json={"transcript_id": TID})
    )
    respx.get(f"{BASE}/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    settings = _fast_settings()
    settings.metadome.poll_soft_deadline_s = 0.05
    svc = _make_service(cache, settings)
    with pytest.raises(NotFoundError) as ei:
        await svc.get_position(TID, 175, response_mode="compact")
    assert ei.value.recovery_action == "switch_tool"
    await svc.aclose()


# ---------------------------------------------------------------------------
# get_position
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_position_returns_fields(cache: ResultCache) -> None:
    """get_position returns sw_dn_ds, domain membership and variant counts."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.get_position(TID, 175, response_mode="standard")
    assert out["protein_pos"] == 175
    assert out["ref_aa"] == "R"
    assert out["sw_dn_ds"] == pytest.approx(0.44289044289044294)
    assert "recommended_citation" in out
    await svc.aclose()


@respx.mock
async def test_get_position_out_of_range_raises_invalid_input(cache: ResultCache) -> None:
    """An out-of-range position raises InvalidInputError."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    with pytest.raises(InvalidInputError):
        await svc.get_position(TID, 99999, response_mode="compact")
    await svc.aclose()


# ---------------------------------------------------------------------------
# get_variant_counts
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_variant_counts_single_position_source_filter(cache: ResultCache) -> None:
    """A single position with source='clinvar' returns only clinvar counts."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.get_variant_counts(
        TID, position=175, source="clinvar", response_mode="standard"
    )
    assert out["positions"][0]["protein_pos"] == 175
    counts = out["positions"][0]["counts"]
    assert "clinvar" in counts
    assert "gnomad" not in counts
    await svc.aclose()


@respx.mock
async def test_get_variant_counts_range_both(cache: ResultCache) -> None:
    """A position range with source='both' returns both count groups, paginated."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.get_variant_counts(
        TID,
        position_start=173,
        position_stop=177,
        source="both",
        response_mode="standard",
    )
    assert out["pagination"]["total"] == 5
    p175 = next(p for p in out["positions"] if p["protein_pos"] == 175)
    assert p175["counts"]["gnomad"]["variant_count"] == 2
    assert p175["counts"]["clinvar"]["variant_count"] == 2
    await svc.aclose()


# ---------------------------------------------------------------------------
# compare_positions
# ---------------------------------------------------------------------------


@respx.mock
async def test_compare_positions_batch_with_per_item_error(cache: ResultCache) -> None:
    """compare_positions returns a row per position; bad ones get per-item errors."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.compare_positions(TID, [175, 248, 99999], response_mode="standard")
    rows = {r["protein_pos"]: r for r in out["comparison"]}
    assert rows[175]["sw_dn_ds"] == pytest.approx(0.44289044289044294)
    assert rows[248]["ref_aa"] == "R"
    assert "error" in rows[99999]
    await svc.aclose()


@respx.mock
async def test_compare_positions_too_many_raises(cache: ResultCache) -> None:
    """Exceeding MAX_BATCH_POSITIONS raises InvalidInputError."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    with pytest.raises(InvalidInputError):
        await svc.compare_positions(TID, list(range(1, 200)), response_mode="compact")
    await svc.aclose()


# ---------------------------------------------------------------------------
# get_domains
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_domains_returns_pfam_list(cache: ResultCache) -> None:
    """get_domains returns the top-level Pfam domains."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.get_domains(TID, response_mode="standard")
    ids = {d["ID"] for d in out["domains"]}
    assert {"PF00870", "PF07710", "PF08563"} <= ids
    assert "recommended_citation" in out
    await svc.aclose()


# ---------------------------------------------------------------------------
# get_meta_domain
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_meta_domain_derives_domains_from_landscape(cache: ResultCache) -> None:
    """When 'domains' is omitted, it is derived from the cached residue."""
    cache.put_result(TID, _load("result_TP53.json"))
    route = respx.post(f"{BASE}/get_metadomain_annotation/").mock(
        return_value=httpx.Response(200, json=_load("metadomain_p175.json"))
    )
    svc = _make_service(cache)
    out = await svc.get_meta_domain(TID, 175, limit=100, offset=0, response_mode="standard")
    # The derived requested_domains must be {"PF00870": [81]}.
    body = json.loads(route.calls.last.request.content)
    assert body["requested_domains"] == {"PF00870": [81]}
    assert body["protein_position"] == 175
    pf = out["meta_domains"]["PF00870"]
    assert pf["normal_variants"]
    assert pf["pathogenic_variants"][0]["gene_name"] == "TP63"
    assert isinstance(pf["pathogenic_variants"][0]["clinvar_ID"], str)
    await svc.aclose()


@respx.mock
async def test_get_meta_domain_non_metadomain_residue_empty(cache: ResultCache) -> None:
    """A residue with no domain mapping returns empty meta-domain lists, no error."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.get_meta_domain(TID, 35, limit=100, offset=0, response_mode="standard")
    assert out["meta_domains"] == {}
    await svc.aclose()


# ---------------------------------------------------------------------------
# summarize_intolerant_regions
# ---------------------------------------------------------------------------


@respx.mock
async def test_summarize_intolerant_regions_finds_run(cache: ResultCache) -> None:
    """summarize finds the constrained DNA-binding stretch and annotates domains."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.summarize_intolerant_regions(
        TID, threshold=0.5, min_run=3, top_n=15, response_mode="standard"
    )
    assert out["regions"], "expected at least one intolerant region"
    covered: set[int] = set()
    for region in out["regions"]:
        covered.update(range(region["start"], region["stop"] + 1))
        assert region["mean_sw_dn_ds"] < 0.5
    assert {173, 174, 175, 176, 177} <= covered
    # Region overlapping the DNA-binding domain is annotated with the Pfam id.
    annotated = any("PF00870" in r.get("domains", []) for r in out["regions"])
    assert annotated
    assert "recommended_citation" in out
    await svc.aclose()
