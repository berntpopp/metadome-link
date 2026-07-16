"""Tests for the MetaDome service read-only "landscape view" operations (Task 6).

Covers the per-landscape view methods of :class:`MetaDomeService`
(``get_position``, ``get_variant_counts``, ``compare_positions``,
``get_domains``, ``get_meta_domain``, ``summarize_intolerant_regions``) plus the
``_require_landscape`` not-ready path they share. Each method is a thin delegator
over :mod:`metadome_link.services.landscape_views`; these tests assert the public
return shape and exception contract through the service.

The service returns **plain dicts** (no ``success``/``_meta`` envelope — that is
the MCP plane's job) and **raises typed exceptions** on error. Upstream is mocked
with respx through a real :class:`MetaDomeClient` (poll intervals collapsed so
deadline tests are instant); the result cache is a real :class:`ResultCache` on a
``tmp_path`` SQLite db.
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
)
from metadome_link.services.metadome_service import MetaDomeService

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
    """A single position with source='clinvar' returns only ClinVar evidence."""
    cache.put_result(TID, _load("result_TP53.json"))
    svc = _make_service(cache)
    out = await svc.get_variant_counts(
        TID, position=175, source="clinvar", response_mode="standard"
    )
    assert out["positions"][0]["protein_pos"] == 175
    evidence = out["positions"][0]["variant_evidence"]
    assert "clinvar" in evidence["residue_level"]
    assert "gnomad" not in evidence["residue_level"]
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
    evidence = p175["variant_evidence"]
    assert evidence["residue_level"]["gnomad"]["available"] is False
    assert evidence["residue_level"]["clinvar"]["variant_count"] == 1
    assert evidence["meta_domain_homolog_aggregate"]["gnomad"]["variant_count"] == 2
    assert evidence["meta_domain_homolog_aggregate"]["clinvar"]["variant_count"] == 2
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
