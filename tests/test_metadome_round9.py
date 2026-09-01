"""Round-9 adversarial tests for selector, pagination, and strict-input contracts."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.api.models import validate_result_document
from metadome_link.exceptions import UpstreamUnavailableError

TID = "ENST00000269305.9"
BASE = "https://www.metadome.app/metadome/api"
FX = pathlib.Path(__file__).parent / "fixtures" / "metadome"


def _load(name: str) -> dict[str, Any]:
    """Load a captured MetaDome response without sharing mutable state."""
    return json.loads((FX / name).read_text())


def test_duplicate_protein_positions_are_rejected() -> None:
    """A landscape cannot contain two ambiguous rows for one residue."""
    result = _load("result_TP53.json")
    result["positional_annotation"].append(dict(result["positional_annotation"][0]))
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        validate_result_document(result)
    assert "protein_pos" in str(exc_info.value.extra["field"])


async def test_explicit_empty_domains_stays_empty_scope(
    facade: Any, call_tool: Any, mocked_metadome: Any
) -> None:
    """An explicit empty map is distinct from omission and must not derive domains."""
    data = await call_tool(
        facade,
        "get_meta_domain",
        {"transcript_id": TID, "position": 175, "domains": {}, "response_mode": "standard"},
    )
    assert data["success"] is True
    assert data["requested_domains"] == {}
    assert data["meta_domains"] == {}
    assert mocked_metadome.post("/get_metadomain_annotation/").call_count == 0


@pytest.mark.parametrize(
    "domains",
    [
        {"PF00870": [-1]},
        {"PF00870": [True]},
        {"PF00870": ["81"]},
        {"PF00870": [999999]},
        {"PF99999": [1]},
        {f"PF{i:05d}": [1] for i in range(33)},
        {"PF00870": list(range(1, 258))},
    ],
)
async def test_explicit_domain_selector_is_finite_and_bound(
    facade: Any, call_tool: Any, domains: dict[str, Any]
) -> None:
    """Malformed, unknown, or oversized selectors fail as invalid input."""
    data = await call_tool(
        facade,
        "get_meta_domain",
        {"transcript_id": TID, "position": 175, "domains": domains},
    )
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


@respx.mock
async def test_metadomain_response_cannot_escape_requested_domains() -> None:
    """Endpoint six output is constrained to the explicit selector map."""
    body = _load("metadomain_p175.json")
    body["PF99999"] = body["PF00870"]
    respx.post(f"{BASE}/get_metadomain_annotation/").mock(
        return_value=httpx.Response(200, json=body)
    )
    client = MetaDomeClient()
    with pytest.raises(UpstreamUnavailableError) as exc_info:
        await client.get_metadomain_annotation(TID, 175, {"PF00870": [81]})
    assert "PF99999" in str(exc_info.value.extra["field"])
    await client.aclose()


async def test_meta_domain_pagination_preserves_selector_and_limit(
    facade: Any, call_tool: Any
) -> None:
    """Forward pages retain the exact selector and page size from the request."""
    data = await call_tool(
        facade,
        "get_meta_domain",
        {
            "transcript_id": TID,
            "position": 175,
            "domains": {"PF00870": [81]},
            "limit": 1,
            "offset": 0,
        },
    )
    assert data["success"] is True
    page = next(
        command
        for command in data["_meta"]["next_commands"]
        if command["tool"] == "get_meta_domain" and command["arguments"].get("offset") == 1
    )
    assert page["arguments"]["domains"] == {"PF00870": [81]}
    assert page["arguments"]["limit"] == 1


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_tolerance_landscape", {"transcript_id": TID, "position_start": 173}),
        ("get_tolerance_landscape", {"transcript_id": TID, "position_stop": 177}),
        ("get_variant_counts", {"transcript_id": TID, "position_start": 173}),
        ("get_variant_counts", {"transcript_id": TID, "position_stop": 177}),
    ],
)
async def test_one_sided_ranges_are_rejected(
    facade: Any, call_tool: Any, tool: str, args: dict[str, Any]
) -> None:
    """A range requires both inclusive bounds; one-sided input is not whole-protein."""
    data = await call_tool(facade, tool, args)
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_position_tolerance", {"transcript_id": TID, "position": True}),
        ("compare_positions", {"transcript_id": TID, "positions": [True]}),
        ("get_meta_domain", {"transcript_id": TID, "position": 175, "limit": True}),
        ("get_tolerance_landscape", {"transcript_id": TID, "position_start": True}),
    ],
)
async def test_fastmcp_integer_arguments_reject_booleans(
    facade: Any, call_tool: Any, tool: str, args: dict[str, Any]
) -> None:
    """JSON booleans are not silently coerced into integer positions or limits."""
    data = await call_tool(facade, tool, args)
    assert data["success"] is False
    assert data["error_code"] == "invalid_input"
