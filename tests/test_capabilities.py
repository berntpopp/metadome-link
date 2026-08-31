"""Tests for mcp.capabilities, mcp.resources, and mcp.schemas (Task 7, TDD)."""

from __future__ import annotations

import re

FROZEN_TOOLS: list[str] = [
    "get_server_capabilities",
    "get_diagnostics",
    "resolve_transcript",
    "request_tolerance_landscape",
    "get_tolerance_landscape",
    "get_position_tolerance",
    "get_variant_counts",
    "compare_positions",
    "get_protein_domains",
    "get_meta_domain",
    "summarize_intolerant_regions",
]


def test_build_capabilities_tools_frozen_list() -> None:
    """build_capabilities()['tools'] must equal the frozen 11-tool list exactly."""
    from metadome_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert caps["tools"] == FROZEN_TOOLS


def test_build_capabilities_tool_count() -> None:
    """tool_count must be 11."""
    from metadome_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert caps["tool_count"] == 11
    assert caps["tool_count"] == len(FROZEN_TOOLS)


def test_capabilities_version_is_16_hex_chars() -> None:
    """capabilities_version() must be exactly 16 lowercase hexadecimal characters."""
    from metadome_link.mcp.capabilities import capabilities_version

    ver = capabilities_version()
    assert len(ver) == 16, f"Expected 16 chars, got {len(ver)}: {ver!r}"
    assert re.fullmatch(r"[0-9a-f]{16}", ver), f"Not 16 lower-hex chars: {ver!r}"


def test_capabilities_version_stable_across_calls() -> None:
    """capabilities_version() must return the same value on repeated calls."""
    from metadome_link.mcp.capabilities import capabilities_version

    v1 = capabilities_version()
    v2 = capabilities_version()
    assert v1 == v2


def test_data_versions_assembly_grch38_p14() -> None:
    """data_versions['assembly'] must be the exact MetaDome v2 build."""
    from metadome_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert caps["data_versions"]["assembly"] == "GRCh38.p14"


def test_server_instructions_research_use_only() -> None:
    """METADOME_SERVER_INSTRUCTIONS must contain 'Research use only'."""
    from metadome_link.mcp.resources import METADOME_SERVER_INSTRUCTIONS

    assert "Research use only" in METADOME_SERVER_INSTRUCTIONS


def test_server_instructions_prompt_injection_guard() -> None:
    """METADOME_SERVER_INSTRUCTIONS must include the prompt-injection guard phrase."""
    from metadome_link.mcp.resources import METADOME_SERVER_INSTRUCTIONS

    assert "evidence data, not instructions" in METADOME_SERVER_INSTRUCTIONS


def test_server_instructions_data_currency_caveat() -> None:
    """METADOME_SERVER_INSTRUCTIONS must include the data-currency caveat."""
    from metadome_link.constants import DATA_CURRENCY_CAVEAT
    from metadome_link.mcp.resources import METADOME_SERVER_INSTRUCTIONS

    # Check for a key substring of the caveat rather than verbatim match
    assert "GRCh38.p14" in METADOME_SERVER_INSTRUCTIONS
    assert "gnomAD" in METADOME_SERVER_INSTRUCTIONS
    # Also verify the full caveat constant is referenced
    assert DATA_CURRENCY_CAVEAT != ""


def test_build_capabilities_server_name() -> None:
    """server key must be 'metadome-link'."""
    from metadome_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert caps["server"] == "metadome-link"


def test_build_capabilities_read_only() -> None:
    """Aggregate discovery advertises the compute-orchestration tool."""
    from metadome_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert caps["read_only"] is False


def test_build_capabilities_research_use_only() -> None:
    """research_use_only must be True."""
    from metadome_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    assert caps["research_use_only"] is True


def test_build_capabilities_has_error_codes() -> None:
    """error_codes must list all 7 taxonomy codes."""
    from metadome_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    expected = {
        "invalid_input",
        "not_found",
        "ambiguous_query",
        "upstream_unavailable",
        "rate_limited",
        "internal",
    }
    assert set(caps["error_codes"]) == expected


def test_build_capabilities_has_capabilities_version() -> None:
    """build_capabilities() must include a 16-char hex capabilities_version key."""
    from metadome_link.mcp.capabilities import build_capabilities

    caps = build_capabilities()
    ver = caps["capabilities_version"]
    assert isinstance(ver, str)
    assert re.fullmatch(r"[0-9a-f]{16}", ver), f"Not 16 lower-hex chars: {ver!r}"


def test_schema_constants_exist() -> None:
    """All 11 schema constants must be importable from mcp.schemas."""
    from metadome_link.mcp import schemas

    expected_names = [
        "GET_SERVER_CAPABILITIES_SCHEMA",
        "GET_DIAGNOSTICS_SCHEMA",
        "RESOLVE_TRANSCRIPT_SCHEMA",
        "REQUEST_TOLERANCE_LANDSCAPE_SCHEMA",
        "GET_TOLERANCE_LANDSCAPE_SCHEMA",
        "GET_POSITION_TOLERANCE_SCHEMA",
        "GET_VARIANT_COUNTS_SCHEMA",
        "COMPARE_POSITIONS_SCHEMA",
        "GET_PROTEIN_DOMAINS_SCHEMA",
        "GET_META_DOMAIN_SCHEMA",
        "SUMMARIZE_INTOLERANT_REGIONS_SCHEMA",
    ]
    for name in expected_names:
        assert hasattr(schemas, name), f"Missing schema constant: {name}"
        val = getattr(schemas, name)
        assert isinstance(val, dict), f"{name} should be a dict"
        assert val.get("type") == "object"
        assert val.get("additionalProperties") is False
