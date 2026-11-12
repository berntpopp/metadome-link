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
import pytest
import respx

from metadome_link.api.models import validate_result_document
from metadome_link.exceptions import UpstreamSchemaError

FX = pathlib.Path(__file__).parent / "fixtures" / "metadome"
BASE = "https://www.metadome.app/metadome/api"
TID = "ENST00000269305.9"


def _load(name: str) -> Any:
    return json.loads((FX / name).read_text())


# ---------------------------------------------------------------------------
# annotations (F-11)
# ---------------------------------------------------------------------------


async def test_request_landscape_annotation_marks_compute_side_effect(facade: Any) -> None:
    """F-11: request_tolerance_landscape POSTs /submit_visualization/ (starts a build).

    It is NOT read-only. It is non-destructive and idempotent (dedupes by
    transcript_id upstream), so readOnlyHint=false, destructiveHint=false,
    idempotentHint=true.
    """
    from fastmcp import Client

    async with Client(facade) as client:
        tools = await client.list_tools()
    ann = next(t for t in tools if t.name == "request_tolerance_landscape").annotations
    assert ann is not None
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is False
    assert ann.idempotentHint is True


async def test_get_landscape_annotation_stays_read_only(facade: Any) -> None:
    """Control: the cache-first poll get_tolerance_landscape remains read-only."""
    from fastmcp import Client

    async with Client(facade) as client:
        tools = await client.list_tools()
    ann = next(t for t in tools if t.name == "get_tolerance_landscape").annotations
    assert ann is not None
    assert ann.readOnlyHint is True


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
    assert data["_meta"]["data_versions"]["assembly"] == "GRCh38.p14"


async def test_request_landscape_processing(
    facade: Any, call_tool: Any, mocked_metadome: respx.MockRouter
) -> None:
    """A still-building transcript reports status='processing' (not an error)."""
    mocked_metadome.get(f"/status/GRCh38.p14/{TID}").mock(
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
    """A FAILURE build status maps to a NON-retryable upstream_unavailable (no retry loop)."""
    mocked_metadome.get(f"/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    mocked_metadome.get(f"/error/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"error": "boom"})
    )
    data = await call_tool(facade, "request_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is False
    assert data["error_code"] == "upstream_unavailable"
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
    assert data["_meta"]["data_versions"]["assembly"] == "GRCh38.p14"
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
    mocked_metadome.get(f"/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "STARTED"})
    )
    mocked_metadome.get(f"/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(404, json={"detail": "not ready"})
    )
    data = await call_tool(facade, "get_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is True
    assert data["status"] == "processing"
    assert data["poll_after_s"] is not None
    assert data["cold_build_warning"]
    # Still building: request (idempotent) then poll again.
    steps = data["_meta"]["next_commands"]
    assert steps[0]["tool"] == "request_tolerance_landscape"
    assert any(
        s["tool"] == "get_tolerance_landscape" and s["arguments"].get("transcript_id") == TID
        for s in steps
    )
    submit = next(
        route for route in mocked_metadome.routes if "/submit_visualization/" in str(route.pattern)
    )
    assert submit.call_count == 0


async def test_get_landscape_absent_is_typed_and_points_to_request_then_poll(
    facade: Any,
    call_tool: Any,
    mocked_metadome: respx.MockRouter,
) -> None:
    """An absent upstream task stays read-only and gives an executable recovery chain."""
    mocked_metadome.get(f"/status/GRCh38.p14/{TID}").mock(return_value=httpx.Response(404))
    data = await call_tool(facade, "get_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is False
    assert data["error_code"] == "not_found"
    assert [step["tool"] for step in data["_meta"]["next_commands"][:2]] == [
        "request_tolerance_landscape",
        "get_tolerance_landscape",
    ]
    submit = next(
        route for route in mocked_metadome.routes if "/submit_visualization/" in str(route.pattern)
    )
    assert submit.call_count == 0


async def test_get_landscape_failure_is_non_retryable(
    facade: Any,
    call_tool: Any,
    mocked_metadome: respx.MockRouter,
) -> None:
    """A FAILURE build status surfaces a NON-retryable upstream_unavailable (no retry loop)."""
    mocked_metadome.get(f"/status/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    mocked_metadome.get(f"/result/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(404, json={"detail": "no result"})
    )
    mocked_metadome.get(f"/error/GRCh38.p14/{TID}").mock(
        return_value=httpx.Response(200, json={"error": "build crashed"})
    )
    data = await call_tool(facade, "get_tolerance_landscape", {"transcript_id": TID})
    assert data["success"] is False
    assert data["error_code"] == "upstream_unavailable"
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
    assert data["_meta"]["data_versions"]["assembly"] == "GRCh38.p14"


# ---------------------------------------------------------------------------
# D5 (acceptance 2026-11-12): AVIL repeats Pfam PF00626; upstream sends
# meta_domain_alignment_depth only on the first occurrence (domains[1..5] lack it).
# ---------------------------------------------------------------------------

AVIL_TID = "ENST00000549994.2"


async def test_get_landscape_avil_repeated_pfam_without_alignment_depth(
    facade: Any, call_tool: Any, mocked_metadome: respx.MockRouter
) -> None:
    """The acceptance call (AVIL, positions 415-435) succeeds on real upstream data."""
    mocked_metadome.get(f"/status/GRCh38.p14/{AVIL_TID}").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )
    mocked_metadome.get(f"/result/GRCh38.p14/{AVIL_TID}").mock(
        return_value=httpx.Response(200, json=_load("result_AVIL.json"))
    )
    data = await call_tool(
        facade,
        "get_tolerance_landscape",
        {"transcript_id": AVIL_TID, "position_start": 415, "position_stop": 435},
    )
    assert data["success"] is True, data
    assert data["gene_name"] == "AVIL"
    domains = data["domains"]
    assert len(domains) == 7
    assert domains[0]["meta_domain_alignment_depth"] == 45
    # Absent upstream stays absent -- never fabricated.
    assert "meta_domain_alignment_depth" not in domains[1]
    assert [p["protein_pos"] for p in data["positional_annotation"]] == list(range(415, 436))


async def test_get_position_tolerance_avil_425(
    facade: Any, call_tool: Any, mocked_metadome: respx.MockRouter
) -> None:
    """The acceptance recovery call (AVIL position 425) succeeds too."""
    mocked_metadome.get(f"/status/GRCh38.p14/{AVIL_TID}").mock(
        return_value=httpx.Response(200, json={"status": "SUCCESS"})
    )
    mocked_metadome.get(f"/result/GRCh38.p14/{AVIL_TID}").mock(
        return_value=httpx.Response(200, json=_load("result_AVIL.json"))
    )
    data = await call_tool(
        facade, "get_position_tolerance", {"transcript_id": AVIL_TID, "position": 425}
    )
    assert data["success"] is True, data


@pytest.mark.parametrize(
    ("mutate", "ok"),
    [
        (lambda d: d.pop("meta_domain_alignment_depth"), True),
        (lambda d: d.pop("ID"), False),
        (lambda d: d.update({"extra": 1}), False),
        (lambda d: d.update({"meta_domain_alignment_depth": -1}), False),
        (lambda d: d.update({"meta_domain_alignment_depth": None}), False),
        (lambda d: d.update({"meta_domain_alignment_depth": True}), False),
    ],
)
def test_result_domain_alignment_depth_is_the_only_optional_field(mutate: Any, ok: bool) -> None:
    """D5: AVIL omits the depth on repeated Pfam ids; nothing else is loosened."""
    doc = json.loads((FX / "result_AVIL.json").read_text())
    mutate(doc["domains"][0])
    if ok:
        validate_result_document(doc)
    else:
        with pytest.raises(UpstreamSchemaError):
            validate_result_document(doc)


#: Acceptance 2026-11-12 E4: an ENST id that exists nowhere (live upstream answers PENDING
#: forever on status, 404 on result, and a generic stub on error until a build is submitted).
UNKNOWN_TID = "ENST00000000000.1"


async def test_get_landscape_unknown_transcript_is_not_found_not_processing(
    facade: Any,
    call_tool: Any,
    mocked_metadome: respx.MockRouter,
) -> None:
    """A transcript MetaDome has no job/result/error for is not_found, not processing."""
    mocked_metadome.get(f"/status/GRCh38.p14/{UNKNOWN_TID}").mock(
        return_value=httpx.Response(200, json={"status": "PENDING"})
    )
    mocked_metadome.get(f"/result/GRCh38.p14/{UNKNOWN_TID}").mock(
        return_value=httpx.Response(404, json={"error": "file not found"})
    )
    data = await call_tool(facade, "get_tolerance_landscape", {"transcript_id": UNKNOWN_TID})
    assert data["success"] is False
    assert data["error_code"] == "not_found"
    assert data["retryable"] is False
    assert data["field"] == "transcript_id"
    assert "resolve_transcript" in data["message"]
    assert "1 hour" not in data["message"]
    # request_tolerance_landscape disambiguates: it starts a build for a real id and
    # reports not_found for an id MetaDome does not know.
    assert [step["tool"] for step in data["_meta"]["next_commands"][:2]] == [
        "request_tolerance_landscape",
        "get_tolerance_landscape",
    ]
    submit = next(
        route for route in mocked_metadome.routes if "/submit_visualization/" in str(route.pattern)
    )
    assert submit.call_count == 0


async def test_unknown_transcript_build_failure_is_not_found_with_resolve_hint(
    facade: Any,
    call_tool: Any,
    mocked_metadome: respx.MockRouter,
) -> None:
    """MetaDome's 'no gene region' build FAILURE names an unknown id: not_found, no retry loop."""
    mocked_metadome.post("/submit_visualization/").mock(
        return_value=httpx.Response(
            200, json={"transcript_id": UNKNOWN_TID, "genome_build": "GRCh38.p14"}
        )
    )
    mocked_metadome.get(f"/status/GRCh38.p14/{UNKNOWN_TID}").mock(
        return_value=httpx.Response(200, json={"status": "FAILURE"})
    )
    mocked_metadome.get(f"/error/GRCh38.p14/{UNKNOWN_TID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": "error running visualization job",
                "stacktrace": (
                    "RuntimeError: No gene region could be build for transcript "
                    f"{UNKNOWN_TID}, genome_build GRCh38.p14, reason: "
                    "GeneRepository.retrieve_gene(transcription_id, genome_build): Expected "
                    f"results but found none for transcription_id '{UNKNOWN_TID}'"
                ),
            },
        )
    )
    for tool in ("request_tolerance_landscape", "get_tolerance_landscape"):
        data = await call_tool(facade, tool, {"transcript_id": UNKNOWN_TID})
        assert data["success"] is False, tool
        assert data["error_code"] == "not_found", tool
        assert data["retryable"] is False
        assert data["field"] == "transcript_id"
        assert "resolve_transcript" in data["message"]
        assert "Traceback" not in data["message"] and "GeneRepository" not in data["message"]
        tools = [step["tool"] for step in data["_meta"]["next_commands"]]
        assert "request_tolerance_landscape" not in tools, tool
