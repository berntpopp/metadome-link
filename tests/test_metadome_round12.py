"""Round-12 regression tests for the final MetaDome review findings."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import httpx
import pytest
import respx

from metadome_link.api.client import MetaDomeClient
from metadome_link.config import ServerSettings
from metadome_link.exceptions import UpstreamSchemaError
from metadome_link.mcp.capabilities import build_capabilities
from metadome_link.services.shaping import char_budget_guard

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "metadome"
TID = "ENST00000269305.9"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def test_budget_trim_advances_empty_page_continuation() -> None:
    payload = {
        "positional_annotation": [{"protein_pos": 1, "blob": "x" * 100_000}],
        "pagination": {
            "total": 5,
            "returned": 1,
            "limit": 1,
            "offset": 0,
            "truncated": True,
            "next_offset": 1,
        },
    }
    shaped = char_budget_guard(payload, max_chars=300)
    assert shaped["positional_annotation"] == []
    assert shaped["pagination"]["returned"] == 0
    assert shaped["pagination"]["next_offset"] == 1
    assert shaped["pagination"]["truncated"] is True
    assert len(json.dumps(shaped)) <= 300


@respx.mock
async def test_nonempty_transcript_response_requires_gene_identity() -> None:
    body = _load("get_transcripts_TP53.json")
    body.pop("gene_name")
    respx.get("https://www.metadome.app/metadome/api/get_transcripts/GRCh38.p14/TP53").mock(
        return_value=httpx.Response(200, json=body)
    )
    client = MetaDomeClient(ServerSettings())
    try:
        with pytest.raises(UpstreamSchemaError):
            await client.get_transcripts("TP53")
    finally:
        await client.aclose()


def test_nested_timeout_environment_accepts_finite_numeric_string(monkeypatch: Any) -> None:
    monkeypatch.setenv("METADOME_LINK_METADOME__REQUEST_TIMEOUT_S", "12.5")
    settings = ServerSettings(_env_file=None)
    assert settings.metadome.request_timeout_s == 12.5


def test_explicit_capability_profile_identity_matches_versions() -> None:
    from metadome_link.constants import DATA_PROFILES

    profile = DATA_PROFILES["GRCh37.p13"]
    capabilities = build_capabilities(
        data_versions=dict(profile.data_versions), data_version=profile.data_version
    )
    assert capabilities["genome_build"] == "GRCh37.p13"
    assert capabilities["data_versions"]["assembly"] == "GRCh37.p13"


async def test_meta_domain_schema_advertises_selector_shape(facade: Any) -> None:
    from fastmcp import Client

    async with Client(facade) as client:
        tool = next(item for item in await client.list_tools() if item.name == "get_meta_domain")
    schema = tool.inputSchema["properties"]["domains"]["anyOf"][0]
    assert schema["maxProperties"] == 32
    assert schema["propertyNames"]["maxLength"] == 64
    assert schema["additionalProperties"]["maxItems"] == 256


def test_citation_release_date_matches_current_release() -> None:
    citation = pathlib.Path("CITATION.cff").read_text()
    assert "version: 0.3.7" in citation
    assert "date-released: '2026-09-02'" in citation


def test_error_taxonomy_docs_have_one_unambiguous_upstream_row() -> None:
    for name in ("docs/architecture.md", "docs/usage.md"):
        text = pathlib.Path(name).read_text()
        rows = [line for line in text.splitlines() if "| `upstream_unavailable` |" in line]
        assert len(rows) == 1
        row = rows[0].lower()
        assert "transient" in row and "invalid schema" in row
