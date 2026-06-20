"""JSON output schemas for the typed MetaDome MCP tools (MCP structured output).

The schemas are deliberately **permissive** (``additionalProperties: true``,
only ``success`` required) because ``response_mode`` projects fields out and the
error envelope is returned by the same tool body and must also validate.
Mirror the mondo-link schema style.
"""

from __future__ import annotations

from typing import Any

_META = {"type": "object", "additionalProperties": True}


def _envelope(**properties: Any) -> dict[str, Any]:
    """A permissive object schema carrying the common envelope keys + extras."""
    props: dict[str, Any] = {
        "success": {"type": "boolean"},
        "_meta": _META,
        "error_code": {"type": "string"},
        "message": {"type": "string"},
        "retryable": {"type": "boolean"},
        "recovery_action": {"type": "string"},
        "field": {"type": "string"},
        "hint": {"type": "string"},
        "candidates": {"type": "array"},
        "recommended_citation": {"type": "string"},
        "data_versions": {"type": "object", "additionalProperties": True},
        **properties,
    }
    return {
        "type": "object",
        "required": ["success"],
        "additionalProperties": True,
        "properties": props,
    }


_STR = {"type": "string"}
_STR_NULL = {"type": ["string", "null"]}
_INT = {"type": "integer"}
_INT_NULL = {"type": ["integer", "null"]}
_NUM = {"type": "number"}
_NUM_NULL = {"type": ["number", "null"]}
_BOOL = {"type": "boolean"}
_ARR = {"type": "array"}
_ARR_NULL = {"type": ["array", "null"]}
_OBJ = {"type": "object", "additionalProperties": True}

# ---------------------------------------------------------------------------
# Shared sub-schemas
# ---------------------------------------------------------------------------

_PAGINATION_BLOCK = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "total": _INT,
        "returned": _INT,
        "limit": _INT,
        "offset": _INT,
        "truncated": _BOOL,
        "next_offset": _INT_NULL,
    },
}

_DOMAIN_ENTRY = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "id": _STR,
        "name": _STR,
        "start": _INT,
        "stop": _INT,
        "metadomain": _BOOL,
        "meta_domain_alignment_depth": _INT,
    },
}

_POSITION_ENTRY = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "protein_pos": _INT,
        "ref_aa": _STR_NULL,
        "sw_dn_ds": _NUM_NULL,
        "sw_coverage": _NUM_NULL,
        "sw_size": _INT,
        "domain_ids": _ARR,
        "variant_count_total": _INT,
    },
}

_VARIANT_ENTRY = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "protein_pos": _INT,
        "clinvar_id": _STR_NULL,
        "clinvar_url": _STR_NULL,
        "gnomad_ac": _INT,
        "gnomad_an": _INT,
        "source": _STR,
    },
}

_INTOLERANT_REGION = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "start": _INT,
        "stop": _INT,
        "length": _INT,
        "mean_sw_dn_ds": _NUM_NULL,
        "domain_ids": _ARR,
        "variant_count_total": _INT,
        "rank": _INT,
    },
}

# ---------------------------------------------------------------------------
# Per-tool schemas (one per tool, 11 total + diagnostics)
# ---------------------------------------------------------------------------

GET_SERVER_CAPABILITIES_SCHEMA = _envelope(
    server=_STR,
    server_version=_STR,
    capabilities_version=_STR,
    data_versions=_OBJ,
    tools=_ARR,
    tool_count=_INT,
    response_modes=_ARR,
    error_codes=_ARR,
    recommended_workflows=_ARR,
    read_only=_BOOL,
    research_use_only=_BOOL,
)

GET_DIAGNOSTICS_SCHEMA = _envelope(
    data_available=_BOOL,
    upstream_reachable=_BOOL,
    cache_stats=_OBJ,
    build=_OBJ,
    metrics=_OBJ,
)

RESOLVE_TRANSCRIPT_SCHEMA = _envelope(
    query=_STR,
    transcripts=_ARR,
    total=_INT,
    canonical_transcript_id=_STR_NULL,
)

REQUEST_TOLERANCE_LANDSCAPE_SCHEMA = _envelope(
    job_id=_STR,
    transcript_id=_STR,
    status=_STR,
    poll_after_s=_NUM_NULL,
    eta_hint=_STR_NULL,
    cold_build_warning=_STR_NULL,
)

GET_TOLERANCE_LANDSCAPE_SCHEMA = _envelope(
    transcript_id=_STR,
    gene_name=_STR_NULL,
    protein_ac=_STR_NULL,
    refseq_ids=_ARR,
    domains={"type": "array", "items": _DOMAIN_ENTRY},
    positional_annotation={"type": "array", "items": _POSITION_ENTRY},
    pagination=_PAGINATION_BLOCK,
    status=_STR_NULL,
    poll_after_s=_NUM_NULL,
)

GET_POSITION_TOLERANCE_SCHEMA = _envelope(
    transcript_id=_STR,
    protein_pos=_INT,
    ref_aa=_STR_NULL,
    sw_dn_ds=_NUM_NULL,
    sw_coverage=_NUM_NULL,
    sw_size=_INT,
    domain_ids=_ARR,
    variant_count_total=_INT,
)

GET_VARIANT_COUNTS_SCHEMA = _envelope(
    transcript_id=_STR,
    source=_STR,
    total=_INT,
    returned=_INT,
    positions={"type": "array", "items": _OBJ},
    pagination=_PAGINATION_BLOCK,
)

COMPARE_POSITIONS_SCHEMA = _envelope(
    transcript_id=_STR,
    positions_requested=_INT,
    results={"type": "array", "items": _OBJ},
)

GET_PROTEIN_DOMAINS_SCHEMA = _envelope(
    transcript_id=_STR,
    gene_name=_STR_NULL,
    domain_count=_INT,
    domains={"type": "array", "items": _DOMAIN_ENTRY},
)

GET_META_DOMAIN_SCHEMA = _envelope(
    transcript_id=_STR,
    protein_pos=_INT,
    domains=_OBJ,
    total_normal_variants=_INT,
    total_pathogenic_variants=_INT,
    pagination=_PAGINATION_BLOCK,
)

SUMMARIZE_INTOLERANT_REGIONS_SCHEMA = _envelope(
    transcript_id=_STR,
    gene_name=_STR_NULL,
    threshold=_NUM,
    min_run=_INT,
    top_n=_INT,
    region_count=_INT,
    regions={"type": "array", "items": _INTOLERANT_REGION},
)
