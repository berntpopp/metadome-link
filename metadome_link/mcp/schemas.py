"""JSON output schemas for the typed MetaDome MCP tools (MCP structured output).

The schemas allow optional projection fields for response modes, while closing
the envelope and nested records against misspelled or stale contract fields.
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
        "recovery": {"type": "string"},
        "field": {"type": "string"},
        "hint": {"type": "string"},
        "allowed_values": {"type": "array"},
        "candidates": {"type": "array"},
        "recommended_citation": {"type": "string"},
        "data_versions": {"type": "object", "additionalProperties": True},
        "data_currency_caveat": {"type": "string"},
        "dropped_summary": {"type": "string"},
        **properties,
    }
    return {
        "type": "object",
        "required": ["success"],
        "additionalProperties": False,
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
    "additionalProperties": False,
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
    "additionalProperties": False,
    "properties": {
        "ID": _STR,
        "Name": _STR,
        "start": _INT,
        "stop": _INT,
        "metadomain": _BOOL,
        "meta_domain_alignment_depth": _INT,
    },
}

_POSITION_ENTRY = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cdna_pos": _STR,
        "chr": _STR,
        "chr_positions": _STR,
        "exon_numbers": _STR,
        "protein_pos": _INT,
        "ref_aa": _STR_NULL,
        "ref_aa_triplet": _STR,
        "ref_codon": _STR,
        "strand": _STR,
        "sw_dn_ds": _NUM_NULL,
        "sw_coverage": _NUM_NULL,
        "sw_size": _INT,
        "domains": _OBJ,
        "ClinVar": _ARR,
    },
}

_VARIANT_ENTRY = {
    "type": "object",
    "additionalProperties": False,
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
    "additionalProperties": False,
    "properties": {
        "start": _INT,
        "stop": _INT,
        "length": _INT,
        "mean_sw_dn_ds": _NUM_NULL,
        "min_sw_dn_ds": _NUM_NULL,
        "domains": _ARR,
        "variant_evidence": _OBJ,
    },
}

# ---------------------------------------------------------------------------
# Per-tool schemas (one per tool, 11 total + diagnostics)
# ---------------------------------------------------------------------------

GET_SERVER_CAPABILITIES_SCHEMA = _envelope(
    server=_STR,
    server_version=_STR,
    build=_OBJ,
    capabilities_version=_STR,
    data_versions=_OBJ,
    tools=_ARR,
    tool_count=_INT,
    response_modes=_ARR,
    error_codes=_ARR,
    recommended_workflows=_ARR,
    read_only=_BOOL,
    research_use_only=_BOOL,
    data_source=_STR,
    data_version=_STR,
    genome_build=_STR,
    data_currency_caveat=_STR,
    research_use_notice=_STR,
    recommended_citation=_STR,
    license=_STR,
    limits=_OBJ,
    default_response_mode=_STR,
    detail=_STR,
    more=_STR,
    async_model=_STR,
    score_semantics=_STR,
    provenance_policy=_STR,
    per_call_meta=_ARR,
    per_call_meta_semantics=_STR,
)

GET_DIAGNOSTICS_SCHEMA = _envelope(
    data_available=_BOOL,
    upstream_reachable=_BOOL,
    cache_stats=_OBJ,
    build=_OBJ,
    metrics=_OBJ,
    data_versions=_OBJ,
    capabilities_version=_STR,
)

RESOLVE_TRANSCRIPT_SCHEMA = _envelope(
    query=_STR,
    transcripts=_ARR,
    canonical_transcript_id=_STR_NULL,
    transcript_id=_STR,
    resolved_from=_STR,
    gene_name=_STR,
    analyzable=_BOOL,
    note=_STR,
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
    cold_build_warning=_STR,
)

GET_POSITION_TOLERANCE_SCHEMA = _envelope(
    transcript_id=_STR,
    cdna_pos=_STR,
    chr=_STR,
    chr_positions=_STR,
    exon_numbers=_STR,
    protein_pos=_INT,
    ref_aa=_STR_NULL,
    ref_aa_triplet=_STR,
    ref_codon=_STR,
    strand=_STR,
    sw_dn_ds=_NUM_NULL,
    sw_coverage=_NUM_NULL,
    sw_size=_INT,
    domains=_OBJ,
    variant_evidence=_OBJ,
)

GET_VARIANT_COUNTS_SCHEMA = _envelope(
    transcript_id=_STR,
    source=_STR,
    positions={"type": "array", "items": _OBJ},
    pagination=_PAGINATION_BLOCK,
)

COMPARE_POSITIONS_SCHEMA = _envelope(
    transcript_id=_STR,
    comparison={"type": "array", "items": _OBJ},
)

GET_PROTEIN_DOMAINS_SCHEMA = _envelope(
    transcript_id=_STR,
    gene_name=_STR_NULL,
    domains={"type": "array", "items": _DOMAIN_ENTRY},
)

GET_META_DOMAIN_SCHEMA = _envelope(
    transcript_id=_STR,
    protein_position=_INT,
    requested_domains=_OBJ,
    meta_domains=_OBJ,
)

SUMMARIZE_INTOLERANT_REGIONS_SCHEMA = _envelope(
    transcript_id=_STR,
    gene_name=_STR_NULL,
    threshold=_NUM,
    min_run=_INT,
    top_n=_INT,
    regions={"type": "array", "items": _INTOLERANT_REGION},
)
