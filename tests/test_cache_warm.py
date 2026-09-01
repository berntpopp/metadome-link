"""Operational cache-warm regressions; every upstream request is respx-mocked."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from metadome_link.api.client import MetaDomeClient
from metadome_link.cache import store
from metadome_link.cache.store import MAX_WARM_CONCURRENCY, MAX_WARM_GENES, ResultCache
from metadome_link.config import ServerSettings
from metadome_link.constants import data_profile
from metadome_link.services.metadome_service import MetaDomeService

TID = "ENST00000269305.9"


def _settings(tmp_path: Path) -> ServerSettings:
    config = ServerSettings(
        cache={
            "db_path": str(tmp_path / "warm.sqlite"),
            "ttl_transcripts_s": 60,
            "lru_transcripts": 2,
            "lru_results": 2,
        },
        _env_file=None,
    )
    config.metadome.poll_initial_interval_s = 0.001
    config.metadome.poll_max_interval_s = 0.002
    config.metadome.poll_soft_deadline_s = 0.01
    return config


def test_warm_gene_validation_deduplicates_and_caps() -> None:
    assert store._normalize_warm_genes(["tp53", "TP53", "BRCA1"]) == ["TP53", "BRCA1"]
    for invalid in ("", "TP 53", "../TP53", "TP53/BRCA1", "A" * 65):
        with pytest.raises(ValueError, match="gene"):
            store._normalize_warm_genes([invalid])
    with pytest.raises(ValueError, match=str(MAX_WARM_GENES)):
        store._normalize_warm_genes([f"GENE{index}" for index in range(MAX_WARM_GENES + 1)])


async def test_warm_uses_service_path_and_repeated_request_hits_disk_cache(
    mocked_metadome: respx.MockRouter, tmp_path: Path
) -> None:
    config = _settings(tmp_path)
    summary = await store._warm_cache(["TP53", "tp53"], config=config)
    assert [(item.gene, item.transcript_id, item.error) for item in summary] == [
        ("TP53", TID, None)
    ]

    transcript_route = mocked_metadome.routes[0]
    status_route = next(
        route for route in mocked_metadome.routes if "/status/" in str(route.pattern)
    )
    result_route = next(
        route for route in mocked_metadome.routes if "/result/" in str(route.pattern)
    )
    assert transcript_route.call_count == 1
    status_calls = status_route.call_count
    result_calls = result_route.call_count

    client = MetaDomeClient(config)
    cache = ResultCache(
        db_path=config.cache.db_path,
        data_version=client.data_version,
        lru_maxsize=config.cache.lru_results,
    )
    service = MetaDomeService(client, cache, settings=config)
    try:
        response = await service.get_landscape(TID, limit=1, offset=0, response_mode="minimal")
        assert response["transcript_id"] == TID
        assert status_route.call_count == status_calls
        assert result_route.call_count == result_calls
    finally:
        await service.aclose()
        cache.close()


async def test_warm_cache_isolated_by_configured_profile(
    mocked_metadome: respx.MockRouter, tmp_path: Path
) -> None:
    config = _settings(tmp_path)
    summary = await store._warm_cache(["TP53"], config=config)
    assert summary[0].error is None

    other = ResultCache(
        db_path=config.cache.db_path,
        data_version=data_profile("GRCh37.p13").data_version,
    )
    try:
        assert other.get_result(TID) is None
        assert other.stats()["on_disk"] == 0
    finally:
        other.close()


async def test_warm_cache_uses_bounded_workers_and_keeps_input_order(
    mocked_metadome: respx.MockRouter, tmp_path: Path
) -> None:
    """Warm work overlaps, never exceeds the fixed bound, and reports deterministically."""
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/metadome/get_transcripts_TP53.json").read_text()
    )
    active = 0
    peak = 0

    async def delayed_resolution(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1
        gene = request.url.path.rsplit("/", maxsplit=1)[-1]
        return httpx.Response(200, json={**fixture, "gene_name": gene})

    genes = [f"GENE{index}" for index in range(8)]
    for gene in genes:
        mocked_metadome.get(f"/get_transcripts/GRCh38.p14/{gene}").mock(
            side_effect=delayed_resolution
        )

    config = _settings(tmp_path)
    config.metadome.politeness_rate_per_s = 1000
    config.metadome.politeness_burst = 1000
    started = time.monotonic()
    outcomes = await store._warm_cache(genes, config=config)
    elapsed = time.monotonic() - started

    assert [outcome.gene for outcome in outcomes] == genes
    assert all(outcome.error is None for outcome in outcomes)
    assert 1 < peak <= MAX_WARM_CONCURRENCY
    assert elapsed < 0.18


async def test_warm_cache_cancellation_closes_workers_client_and_cache(
    mocked_metadome: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cancelling the parent tears down fixed workers and both owned resources."""
    entered = asyncio.Event()
    request_cancelled = asyncio.Event()
    service_closed = asyncio.Event()
    cache_closed = asyncio.Event()

    async def blocked(_: httpx.Request) -> httpx.Response:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            request_cancelled.set()
        raise AssertionError("unreachable")

    original_aclose = MetaDomeService.aclose
    original_close = ResultCache.close

    async def tracked_aclose(self: MetaDomeService) -> None:
        await original_aclose(self)
        service_closed.set()

    def tracked_close(self: ResultCache) -> None:
        original_close(self)
        cache_closed.set()

    monkeypatch.setattr(MetaDomeService, "aclose", tracked_aclose)
    monkeypatch.setattr(ResultCache, "close", tracked_close)
    mocked_metadome.get("/get_transcripts/GRCh38.p14/GENE0").mock(side_effect=blocked)

    task = asyncio.create_task(store._warm_cache(["GENE0"], config=_settings(tmp_path)))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert request_cancelled.is_set()
    assert service_closed.is_set()
    assert cache_closed.is_set()


def test_warm_cli_reports_partial_failure_and_exits_nonzero(
    mocked_metadome: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mocked_metadome.get("/get_transcripts/GRCh38.p14/BRCA1").mock(return_value=httpx.Response(404))
    monkeypatch.setattr(store, "settings", _settings(tmp_path))

    result = CliRunner().invoke(store.app, ["warm", "TP53", "BRCA1"])

    assert result.exit_code == 1
    assert f"warmed TP53 -> {TID}" in result.stdout
    assert "failed BRCA1" in result.stderr
    cache = ResultCache(
        db_path=str(tmp_path / "warm.sqlite"),
        data_version=data_profile("GRCh38.p14").data_version,
    )
    try:
        assert cache.cached_transcript_ids() == [TID]
    finally:
        cache.close()
