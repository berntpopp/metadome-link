"""Closed JSON output schemas for the MetaDome MCP tools."""

from __future__ import annotations

from typing import Any

_META = {
    "type": "object",
    "required": ["tool", "request_id", "data_versions", "unsafe_for_clinical_use"],
    "properties": {
        "tool": {"type": "string", "minLength": 1},
        "request_id": {"type": "string", "minLength": 1},
        "data_versions": {
            "type": "object",
            "required": ["assembly", "metadome_app"],
            "additionalProperties": {"type": "string"},
        },
        "unsafe_for_clinical_use": {"const": True},
        "elapsed_ms": {"type": "integer", "minimum": 0},
        "capabilities_version": {"type": "string", "minLength": 1},
        "next_commands": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tool", "arguments"],
                "properties": {
                    "tool": {"type": "string", "minLength": 1},
                    "arguments": {"type": "object"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def _envelope(**properties: Any) -> dict[str, Any]:
    """Return a closed success/error envelope discriminated by ``success``."""
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
        "allowed_values": {"type": "array", "items": {"type": ["string", "integer"]}},
        "candidates": {"type": "array", "items": {"type": "object"}},
        "recommended_citation": {"type": "string"},
        "data_currency_caveat": {"type": "string"},
        "dropped_summary": {"type": "string"},
        **properties,
    }
    return {
        "type": "object",
        "properties": props,
        "required": ["success", "_meta"],
        "additionalProperties": False,
        "oneOf": [
            {"properties": {"success": {"const": True}}},
            {
                "required": ["success", "error_code", "message", "retryable", "recovery_action"],
                "properties": {
                    "success": {"const": False},
                    "error_code": {
                        "enum": [
                            "invalid_input",
                            "not_found",
                            "ambiguous_query",
                            "upstream_unavailable",
                            "rate_limited",
                            "internal",
                        ]
                    },
                    "message": {"type": "string", "minLength": 1},
                    "retryable": {"type": "boolean"},
                    "recovery_action": {"type": "string", "minLength": 1},
                },
            },
        ],
    }


_STR = {"type": "string"}
_STR_NULL = {"type": ["string", "null"]}
_INT = {"type": "integer"}
_INT_NULL = {"type": ["integer", "null"]}
_NUM = {"type": "number"}
_NUM_NULL = {"type": ["number", "null"]}
_BOOL = {"type": "boolean"}
_STR_ARRAY = {"type": "array", "items": _STR}
_DATA_VERSIONS = {
    "type": "object",
    "required": ["assembly", "metadome_app"],
    "additionalProperties": {"type": "string"},
}
_BUILD = {
    "type": "object",
    "required": ["version", "git_sha", "built_at"],
    "properties": {"version": _STR, "git_sha": _STR, "built_at": _STR_NULL},
    "additionalProperties": False,
}
_LIMITS = {
    "type": "object",
    "properties": {"max_batch_positions": _INT, "default_page_limit": _INT, "max_page_limit": _INT},
    "additionalProperties": False,
}
_TRANSCRIPT = {
    "type": "object",
    "properties": {
        "gencode_id": _STR,
        "aa_length": _INT,
        "has_protein_data": _BOOL,
        "mane_transcript_type": _STR,
        "refseq_ids": _STR_ARRAY,
        "canonical": _BOOL,
    },
    "additionalProperties": False,
}
_TOOL_MODES = {
    "type": "object",
    "properties": {"read_only": _STR_ARRAY, "compute_orchestration": _STR_ARRAY},
    "additionalProperties": False,
}
_METRICS = {
    "type": "object",
    "properties": {
        "requests": _INT,
        "errors": _INT,
        "error_rate": _NUM_NULL,
        "latency_ms": {
            "type": "object",
            "properties": dict.fromkeys(("p50", "p95", "p99", "max", "sampled"), _INT),
            "additionalProperties": False,
        },
        "per_tool": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {"requests": _INT, "errors": _INT},
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}
_META_VARIANT = {
    "type": "object",
    "propertyNames": {
        "enum": [
            "allele_count",
            "allele_number",
            "alt",
            "alt_aa",
            "alt_aa_triplet",
            "alt_codon",
            "cdna_pos",
            "chr",
            "chr_positions",
            "gene_name",
            "pos",
            "protein_pos",
            "ref",
            "ref_aa",
            "ref_aa_triplet",
            "ref_codon",
            "strand",
            "type",
            "clinvar_ID",
        ]
    },
    "additionalProperties": {"type": ["number", "string", "integer"]},
}

_PAGINATION_BLOCK = {
    "type": "object",
    "propertyNames": {"enum": ["total", "returned", "limit", "offset", "truncated", "next_offset"]},
    "additionalProperties": {"type": ["integer", "boolean", "null"]},
}

_META_DOMAIN_BLOCK = {
    "type": "object",
    "properties": {
        "alignment_depth": _INT,
        "normal_variants": {"type": "array", "items": {"$ref": "#/$defs/metaVariant"}},
        "pathogenic_variants": {"type": "array", "items": {"$ref": "#/$defs/metaVariant"}},
        "pagination": {
            "type": "object",
            "properties": {
                "normal_variants": {"$ref": "#/$defs/pagination"},
                "pathogenic_variants": {"$ref": "#/$defs/pagination"},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
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
        "protein_pos": _INT,
        "ref_aa": _STR_NULL,
        "ref_aa_triplet": _STR,
        "ref_codon": _STR,
        "strand": _STR,
        "sw_dn_ds": _NUM_NULL,
        "sw_coverage": _NUM_NULL,
        "sw_size": _INT,
        "domains": {"type": "object", "additionalProperties": {"type": ["object", "null"]}},
        "ClinVar": {"type": "array", "items": {"type": "object"}},
    },
}

_VARIANT_EVIDENCE = {
    "type": "object",
    "propertyNames": {"enum": ["residue_level", "meta_domain_homolog_aggregate"]},
    "additionalProperties": {"type": "object"},
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

_CLINVAR_ENTRY = {
    "type": "object",
    "propertyNames": {
        "enum": [
            "alt",
            "alt_aa",
            "alt_aa_triplet",
            "alt_codon",
            "clinvar_ID",
            "pos",
            "ref",
            "type",
            "url",
        ]
    },
    "additionalProperties": {"type": ["string", "integer", "number"]},
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
        "domains": {"type": "array", "items": _STR},
        "variant_evidence": _VARIANT_EVIDENCE,
    },
}

GET_SERVER_CAPABILITIES_SCHEMA = _envelope(
    server=_STR,
    server_version=_STR,
    build=_BUILD,
    capabilities_version=_STR,
    data_versions=_DATA_VERSIONS,
    tools=_STR_ARRAY,
    tool_count=_INT,
    response_modes=_STR_ARRAY,
    error_codes=_STR_ARRAY,
    recommended_workflows=_STR_ARRAY,
    read_only=_BOOL,
    tool_modes=_TOOL_MODES,
    research_use_only=_BOOL,
    data_source=_STR,
    data_version=_STR,
    genome_build=_STR,
    data_currency_caveat=_STR,
    research_use_notice=_STR,
    recommended_citation=_STR,
    license=_STR,
    limits=_LIMITS,
    default_response_mode=_STR,
    detail=_STR,
    more=_STR,
    async_model=_STR,
    score_semantics=_STR,
    provenance_policy=_STR,
    per_call_meta=_STR_ARRAY,
    per_call_meta_semantics=_STR,
)

GET_DIAGNOSTICS_SCHEMA = _envelope(
    cache_stats={
        "type": "object",
        "properties": {"on_disk": _INT, "lru_size": _INT, "data_version": _STR},
        "additionalProperties": False,
    },
    build=_BUILD,
    metrics=_METRICS,
    data_versions=_DATA_VERSIONS,
    capabilities_version=_STR,
)

RESOLVE_TRANSCRIPT_SCHEMA = _envelope(
    query=_STR,
    transcripts={"type": "array", "items": _TRANSCRIPT},
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
    refseq_ids=_STR_ARRAY,
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
    domains={"type": "object", "additionalProperties": {"type": "object"}},
    variant_evidence=_VARIANT_EVIDENCE,
)

GET_VARIANT_COUNTS_SCHEMA = _envelope(
    transcript_id=_STR,
    source=_STR,
    positions={
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "protein_pos": _INT_NULL,
                "ref_aa": _STR_NULL,
                "sw_dn_ds": _NUM_NULL,
                "domain_ids": {"type": "array", "items": _STR},
                "variant_evidence": _VARIANT_EVIDENCE,
                "clinvar_variants": {"type": "array", "items": _CLINVAR_ENTRY},
            },
            "additionalProperties": False,
        },
    },
    pagination=_PAGINATION_BLOCK,
)

COMPARE_POSITIONS_SCHEMA = _envelope(
    transcript_id=_STR,
    comparison={
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "protein_pos": _INT,
                "ref_aa": _STR_NULL,
                "sw_dn_ds": _NUM_NULL,
                "domain_ids": {"type": "array", "items": _STR},
                "variant_evidence": _VARIANT_EVIDENCE,
                "error": _STR,
            },
            "additionalProperties": False,
        },
    },
)

GET_PROTEIN_DOMAINS_SCHEMA = _envelope(
    transcript_id=_STR,
    gene_name=_STR_NULL,
    domains={"type": "array", "items": _DOMAIN_ENTRY},
)

GET_META_DOMAIN_SCHEMA = _envelope(
    transcript_id=_STR,
    protein_position=_INT,
    requested_domains={"type": "object", "additionalProperties": {"type": "array", "items": _INT}},
    meta_domains={"type": "object", "additionalProperties": _META_DOMAIN_BLOCK},
)
GET_META_DOMAIN_SCHEMA["$defs"] = {"metaVariant": _META_VARIANT, "pagination": _PAGINATION_BLOCK}

SUMMARIZE_INTOLERANT_REGIONS_SCHEMA = _envelope(
    transcript_id=_STR,
    gene_name=_STR_NULL,
    threshold=_NUM,
    min_run=_INT,
    top_n=_INT,
    regions={"type": "array", "items": _INTOLERANT_REGION},
)
