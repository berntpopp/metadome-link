"""Shared test fixtures for the MCP tool surface (Task 8; reused by Tasks 9-13).

The fixture chain mirrors ``tests/test_metadome_service.py``: a real
:class:`MetaDomeClient` over a **respx-mocked** MetaDome API, a real
:class:`ResultCache` on a ``tmp_path`` SQLite db, and a :class:`MetaDomeService`
composed from both. The ``facade`` fixture wires that service into a real
``FastMCP`` instance via ``create_metadome_mcp(service_factory=...)``, and
``call_tool`` drives it through an in-memory ``fastmcp.Client``.

Usage in a tool test::

    async def test_xxx(facade, call_tool):
        data = await call_tool(facade, "get_server_capabilities", {})
        assert data["success"] is True

The ``mocked_metadome`` fixture exposes the live respx router so a test can
override a route (e.g. force a PENDING status or a 404) before calling a tool;
by default all six endpoints return the bundled fixtures with a SUCCESS status.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.cache.store import ResultCache
from metadome_link.config import ServerSettings
from metadome_link.mcp import metrics
from metadome_link.mcp.facade import create_metadome_mcp
from metadome_link.mcp.service_adapters import set_metadome_service
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


@pytest.fixture(autouse=True)
def _reset_metrics() -> Iterator[None]:
    """Keep the process-wide metrics collector clean between tests."""
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
def mocked_metadome() -> Iterator[respx.MockRouter]:
    """A respx router mocking the six MetaDome endpoints from the bundled fixtures.

    Defaults: ``get_transcripts/TP53`` → fixture, ``submit_visualization`` echoes
    the id, ``status`` → SUCCESS, ``result`` → fixture, ``error`` → a stub,
    ``get_metadomain_annotation`` → fixture. Tests may re-mock any route on the
    yielded router to exercise alternate paths (PENDING/FAILURE/404/unknown gene).
    """
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.get("/get_transcripts/TP53").mock(
            return_value=httpx.Response(200, json=_load("get_transcripts_TP53.json"))
        )
        router.post("/submit_visualization/").mock(
            return_value=httpx.Response(200, json={"transcript_id": TID})
        )
        router.get(f"/status/{TID}/").mock(
            return_value=httpx.Response(200, json={"status": "SUCCESS"})
        )
        router.get(f"/result/{TID}/").mock(
            return_value=httpx.Response(200, json=_load("result_TP53.json"))
        )
        router.get(f"/error/{TID}/").mock(
            return_value=httpx.Response(200, json={"error": "stub"})
        )
        router.post("/get_metadomain_annotation/").mock(
            return_value=httpx.Response(200, json=_load("metadomain_p175.json"))
        )
        yield router


@pytest.fixture
async def metadome_service(
    mocked_metadome: respx.MockRouter,
    tmp_path: pathlib.Path,
) -> AsyncIterator[MetaDomeService]:
    """A real MetaDomeService over the respx-mocked client + a temp result cache."""
    settings = _fast_settings()
    client = MetaDomeClient(settings)
    cache = ResultCache(db_path=str(tmp_path / "cache.sqlite"))
    service = MetaDomeService(client, cache, settings=settings)
    try:
        yield service
    finally:
        await service.aclose()
        cache.close()


@pytest.fixture
def facade(metadome_service: MetaDomeService) -> Iterator[Any]:
    """A FastMCP facade with the fixture service injected; cleans up after."""
    mcp = create_metadome_mcp(service_factory=lambda: metadome_service)
    yield mcp
    set_metadome_service(None)


@pytest.fixture
def call_tool() -> Callable[[Any, str, dict[str, Any]], Awaitable[Any]]:
    """An in-memory ``fastmcp.Client`` tool caller.

    Returns the tool's structured payload as a plain ``dict`` — the same
    ``{success, _meta, ...}`` mapping the tool body produced, including error
    envelopes (``raise_on_error=False``). ``structured_content`` is the raw dict;
    ``data`` is the schema-typed model, so the dict is preferred for assertions.
    """
    from fastmcp import Client

    async def _call(mcp: Any, name: str, args: dict[str, Any]) -> Any:
        async with Client(mcp) as client:
            res = await client.call_tool(name, args, raise_on_error=False)
        if isinstance(res.structured_content, dict):
            return res.structured_content
        return res.data

    return _call
