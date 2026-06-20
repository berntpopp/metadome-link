"""Tolerance-landscape tool tests through the real FastMCP facade (Task 10).

These exercise the full MCP path: facade -> envelope -> landscape tool body ->
injected (respx-mocked) service. They cover the async split: the
``request_tolerance_landscape`` handle (ready vs processing) and the
``get_tolerance_landscape`` poll (processing-state success, ready landscape with
domains + paginated positions, a position-range slice, and a FAILURE -> upstream
error).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import httpx
import respx

FX = pathlib.Path(__file__).parent / "fixtures" / "metadome"
BASE = "https://stuart.radboudumc.nl/metadome/api"
TID = "ENST00000269305.4"


def _load(name: str) -> Any:
    return json.loads((FX / name).read_text())


# ---------------------------------------------------------------------------
# request_tolerance_landscape
# ---------------------------------------------------------------------------


async def test_request_landscape_ready(facade: Any, call_tool: Any) -> None:
    """A pre-built transcript returns status='ready' with the poll handle + chain."""
    data = await call_tool(facade, "request_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is True
    assert data["status"] == "ready"
    assert data["job_id"] == TID
    assert data["transcript_id"] == TID
    assert data["recommended_citation"]
    # The success chain points at the poll tool keyed on the same transcript.
    steps = data["_meta"]["next_commands"]
    assert any(
        s["tool"] == "get_tolerance_landscape" and s["arguments"].get("transcript_id") == TID
        for s in steps
    )
    assert data["_meta"]["data_versions"]["assembly"] == "GRCh37"


async def test_request_landscape_processing(
    facade: Any, call_tool: Any, mocked_metadome: respx.MockRouter
) -> None:
    """A still-building transcript reports status='processing' (not an error)."""
    mocked_metadome.get(f"/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    data = await call_tool(facade, "request_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is True
    assert data["status"] == "processing"
    assert data["poll_after_s"] is not None
    assert data["cold_build_warning"]


async def test_request_landscape_failure_is_non_retryable(
    facade: Any, call_tool: Any, mocked_metadome: respx.MockRouter
) -> None:
    """A FAILURE build status maps to a NON-retryable data_unavailable (no retry loop)."""
    mocked_metadome.get(f"/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    mocked_metadome.get(f"/error/{TID}/").mock(
        return_value=httpx.Response(200, json={"error": "boom"})
    )
    data = await call_tool(facade, "request_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is False
    assert data["error_code"] == "data_unavailable"
    assert data["retryable"] is False


async def test_request_landscape_bad_id_is_invalid_input(facade: Any, call_tool: Any) -> None:
    """An unversioned ENST id fails locally as invalid_input."""
    data = await call_tool(
        facade, "request_tolerance_landscape", {"transcript_id": "ENST00000269305"}
    )
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


# ---------------------------------------------------------------------------
# get_tolerance_landscape
# ---------------------------------------------------------------------------


async def test_get_landscape_ready_returns_domains_and_positions(
    facade: Any, call_tool: Any
) -> None:
    """A ready landscape returns domains + paginated positions + data_versions."""
    data = await call_tool(facade, "get_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is True
    assert data["transcript_id"] == TID
    assert data["gene_name"] == "TP53"
    assert isinstance(data["domains"], list) and len(data["domains"]) == 3
    positions = data["positional_annotation"]
    assert isinstance(positions, list) and positions
    assert all("protein_pos" in p for p in positions)
    pg = data["pagination"]
    assert pg["total"] == 20
    assert pg["returned"] == len(positions)
    assert data["_meta"]["data_versions"]["assembly"] == "GRCh37"
    # Ready -> success chain suggests downstream position/domain tools.
    tools = {s["tool"] for s in data["_meta"]["next_commands"]}
    assert "get_position_tolerance" in tools
    assert "get_protein_domains" in tools


async def test_get_landscape_pagination_truncates(facade: Any, call_tool: Any) -> None:
    """A small limit truncates the page and exposes a forward-page next_command."""
    data = await call_tool(
        facade,
        "get_tolerance_landscape",
        {"transcript_id": TID, "limit": 5, "offset": 0},
    )
    assert data["success"] is True
    pg = data["pagination"]
    assert pg["total"] == 20
    assert pg["returned"] == 5
    assert pg["truncated"] is True
    assert pg["next_offset"] == 5
    # The truncated page offers a paging step on the same tool.
    steps = data["_meta"]["next_commands"]
    assert any(
        s["tool"] == "get_tolerance_landscape" and s["arguments"].get("offset") == 5 for s in steps
    )


async def test_get_landscape_slice_by_position_range(facade: Any, call_tool: Any) -> None:
    """position_start/stop slices the landscape to the requested inclusive range."""
    data = await call_tool(
        facade,
        "get_tolerance_landscape",
        {"transcript_id": TID, "position_start": 173, "position_stop": 177},
    )
    assert data["success"] is True
    positions = data["positional_annotation"]
    poss = [p["protein_pos"] for p in positions]
    assert poss == [173, 174, 175, 176, 177]
    assert data["pagination"]["total"] == 5
    assert data["pagination"]["truncated"] is False


async def test_get_landscape_processing_state(
    facade: Any,
    call_tool: Any,
    mocked_metadome: respx.MockRouter,
) -> None:
    """A still-building job is a first-class success:true,status='processing'."""
    # No cached result + status never reaches SUCCESS -> processing state.
    mocked_metadome.get(f"/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    mocked_metadome.get(f"/result/{TID}/").mock(
        return_value=httpx.Response(404, json={"detail": "not ready"})
    )
    data = await call_tool(facade, "get_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is True
    assert data["status"] == "processing"
    assert data["poll_after_s"] is not None
    assert data["cold_build_warning"]
    # next_commands re-suggests this same tool (poll self).
    steps = data["_meta"]["next_commands"]
    assert any(
        s["tool"] == "get_tolerance_landscape" and s["arguments"].get("transcript_id") == TID
        for s in steps
    )


async def test_get_landscape_failure_is_non_retryable(
    facade: Any,
    call_tool: Any,
    mocked_metadome: respx.MockRouter,
) -> None:
    """A FAILURE build status surfaces a NON-retryable data_unavailable (no retry loop)."""
    mocked_metadome.get(f"/status/{TID}/").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    mocked_metadome.get(f"/result/{TID}/").mock(
        return_value=httpx.Response(404, json={"detail": "no result"})
    )
    mocked_metadome.get(f"/error/{TID}/").mock(
        return_value=httpx.Response(200, json={"error": "build crashed"})
    )
    data = await call_tool(facade, "get_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is False
    assert data["error_code"] == "data_unavailable"
    assert data["retryable"] is False


async def test_get_landscape_bad_id_is_invalid_input(facade: Any, call_tool: Any) -> None:
    """An unversioned ENST id fails locally as invalid_input."""
    data = await call_tool(facade, "get_tolerance_landscape", {"transcript_id": "not-an-enst"})
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


async def test_get_landscape_position_below_one_rejected(facade: Any, call_tool: Any) -> None:
    """position_start below 1 is rejected by the ge=1 arg constraint."""
    data = await call_tool(
        facade,
        "get_tolerance_landscape",
        {"transcript_id": TID, "position_start": 0, "position_stop": 5},
    )
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


async def test_get_landscape_minimal_mode_drops_next_commands(facade: Any, call_tool: Any) -> None:
    """response_mode='minimal' is the documented opt-out from next_commands."""
    data = await call_tool(
        facade,
        "get_tolerance_landscape",
        {"transcript_id": TID, "response_mode": "minimal"},
    )
    assert data["success"] is True
    assert "next_commands" not in data["_meta"]
    assert data["_meta"]["data_versions"]["assembly"] == "GRCh37"
