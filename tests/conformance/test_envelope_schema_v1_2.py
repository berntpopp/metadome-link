"""Response-Envelope v1.2: every data tool's result validates against the published schema.

The schema is vendored from berntpopp/genefoundry-envelope, tag v1.2.0
(``envelope-v1.2.schema.json``); its digest is pinned in the sibling ``.sha256`` file.
Each tool is called in-process against the mocked MetaDome upstream.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from metadome_link import provenance
from metadome_link.mcp.capabilities import TOOLS
from tests.unit.test_output_schemas import _ERROR_ARGS, _SUCCESS_ARGS

_HERE = Path(__file__).parent
_SCHEMA_FILE = _HERE / "envelope-v1.2.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_FILE.read_text(encoding="utf-8")))

_OPS_TOOLS = {"get_server_capabilities", "get_diagnostics"}  # outside the v1.2 rule
_DATA_TOOLS = sorted(set(TOOLS) - _OPS_TOOLS)
_PROVENANCE = ("source", "data_version", "retrieved_at")
_TID = _SUCCESS_ARGS["get_tolerance_landscape"]["transcript_id"]


def _violations(envelope: dict[str, Any]) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in _VALIDATOR.iter_errors(envelope)
    ]


def test_vendored_schema_is_the_pinned_release() -> None:
    pin = (_HERE / "envelope-v1.2.schema.sha256").read_text(encoding="utf-8").strip()
    assert hashlib.sha256(_SCHEMA_FILE.read_bytes()).hexdigest() == pin


@pytest.mark.parametrize("mode", ["minimal", "compact", "full"])
@pytest.mark.parametrize("tool", _DATA_TOOLS)
async def test_data_tool_result_validates(
    facade: Any, call_tool: Any, tool: str, mode: str
) -> None:
    envelope = await call_tool(facade, tool, {**_SUCCESS_ARGS[tool], "response_mode": mode})
    assert envelope["success"] is True
    assert _violations(envelope) == []
    for field in _PROVENANCE:
        assert isinstance(envelope["_meta"][field], str) and envelope["_meta"][field], field
    assert envelope["_meta"]["source"] == "metadome"


async def test_ops_tools_carry_no_provenance(facade: Any, call_tool: Any) -> None:
    for tool in sorted(_OPS_TOOLS):
        meta = (await call_tool(facade, tool, {}))["_meta"]
        assert not set(_PROVENANCE) & set(meta)


@pytest.mark.parametrize("tool", _DATA_TOOLS)
async def test_error_result_validates(facade: Any, call_tool: Any, tool: str) -> None:
    for arguments in (_ERROR_ARGS[tool], {**_SUCCESS_ARGS[tool], "bogus": 1}):
        envelope = await call_tool(facade, tool, {**arguments, "response_mode": "minimal"})
        assert envelope["success"] is False
        assert list(_VALIDATOR.iter_errors(envelope)) == []


async def test_cached_landscape_keeps_its_original_fetch_time(facade: Any, call_tool: Any) -> None:
    from metadome_link.mcp.service_adapters import get_metadome_service

    arguments = {"transcript_id": _TID}
    first = await call_tool(facade, "get_tolerance_landscape", arguments)
    cache = get_metadome_service()._cache
    cache._lru.clear()
    cache._conn.execute("UPDATE results SET fetched_at = '2020-01-01T00:00:00+00:00'")
    second = await call_tool(facade, "get_tolerance_landscape", arguments)  # served from disk
    third = await call_tool(facade, "get_tolerance_landscape", arguments)  # served from the LRU
    assert first["_meta"]["retrieved_at"] >= "2026"
    assert second["_meta"]["retrieved_at"] == "2020-01-01T00:00:00Z"
    assert third["_meta"]["retrieved_at"] == "2020-01-01T00:00:00Z"


def test_retrieved_at_is_the_oldest_fetch() -> None:
    provenance.begin()
    provenance.fetched("2024-05-01T00:00:00Z")
    provenance.fetched("2023-05-01T00:00:00Z")
    assert provenance.retrieved_at() == "2023-05-01T00:00:00Z"
