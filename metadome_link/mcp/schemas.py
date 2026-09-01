"""Discriminated, recursively closed output schemas for all MetaDome tools."""

from __future__ import annotations

from metadome_link.mcp.schema_defs import (
    BOOL,
    BUILD,
    CLINVAR_VARIANT,
    DOMAIN,
    DOMAIN_MEMBERSHIP,
    EVIDENCE_DEFS,
    INT,
    INTOLERANT_REGION,
    LATENCY,
    LIMITS,
    META_DOMAIN,
    META_VARIANT_COMMON,
    METRICS,
    NORMAL_META_VARIANT,
    NUM,
    NUM_NULL,
    PAGINATION,
    PATHOGENIC_META_VARIANT,
    POSITION,
    POSITION_DOMAIN,
    STR,
    STR_ARRAY,
    STR_NULL,
    TALLY,
    TOOL_MODES,
    TRANSCRIPT,
    closed,
    output_schema,
)

_CITATION = {"recommended_citation": STR}
_CAVEAT = {"data_currency_caveat": STR}

GET_SERVER_CAPABILITIES_SCHEMA = output_schema(
    {
        "server": STR,
        "server_version": STR,
        "build": {"$ref": "#/$defs/b"},
        "capabilities_version": STR,
        "data_versions": {"$ref": "#/$defs/V"},
        "tools": STR_ARRAY,
        "tool_count": INT,
        "response_modes": STR_ARRAY,
        "error_codes": STR_ARRAY,
        "recommended_workflows": STR_ARRAY,
        "read_only": BOOL,
        "tool_modes": {"$ref": "#/$defs/tm"},
        "research_use_only": BOOL,
        "data_source": STR,
        "data_version": STR,
        "genome_build": STR,
        "data_currency_caveat": STR,
        "research_use_notice": STR,
        "recommended_citation": STR,
        "license": STR,
        "limits": {"$ref": "#/$defs/l"},
        "default_response_mode": STR,
        "detail": STR,
        "more": STR,
        "async_model": STR,
        "score_semantics": STR,
        "provenance_policy": STR,
        "per_call_meta": STR_ARRAY,
        "per_call_meta_semantics": STR,
    },
    (
        "server",
        "server_version",
        "build",
        "capabilities_version",
        "data_versions",
        "tools",
        "tool_count",
        "response_modes",
        "error_codes",
        "read_only",
        "tool_modes",
        "research_use_only",
        "data_source",
        "data_version",
        "genome_build",
        "recommended_citation",
        "license",
        "limits",
        "default_response_mode",
        "detail",
    ),
    defs={"b": BUILD, "l": LIMITS, "tm": TOOL_MODES},
)

GET_DIAGNOSTICS_SCHEMA = output_schema(
    {
        "cache_stats": closed(
            {"on_disk": INT, "lru_size": INT, "data_version": STR},
            ("on_disk", "lru_size", "data_version"),
        ),
        "build": {"$ref": "#/$defs/b"},
        "metrics": {"$ref": "#/$defs/x"},
        "data_versions": {"$ref": "#/$defs/V"},
        "capabilities_version": STR,
    },
    ("cache_stats", "build", "metrics", "data_versions", "capabilities_version"),
    defs={
        "b": BUILD,
        "x": METRICS,
        "y": LATENCY,
        "z": TALLY,
    },
)

RESOLVE_TRANSCRIPT_SCHEMA = output_schema(
    {
        "transcripts": {"type": "array", "items": {"$ref": "#/$defs/t"}},
        "canonical_transcript_id": STR_NULL,
        "transcript_id": STR,
        "resolved_from": {"enum": ["gene", "id"]},
        "gene_name": STR,
        "analyzable": BOOL,
        "note": STR,
        **_CITATION,
    },
    ("resolved_from", "recommended_citation"),
    constraint={
        "oneOf": [
            {"properties": {"resolved_from": {"const": "id"}}, "required": ["transcript_id"]},
            {
                "properties": {"resolved_from": {"const": "gene"}},
                "required": ["gene_name", "analyzable", "transcripts"],
            },
        ]
    },
    defs={"t": TRANSCRIPT},
    candidates=True,
)

REQUEST_TOLERANCE_LANDSCAPE_SCHEMA = output_schema(
    {
        "job_id": STR,
        "transcript_id": STR,
        "status": {"enum": ["ready", "processing"]},
        "poll_after_s": NUM,
        "eta_hint": STR,
        "cold_build_warning": STR,
        **_CITATION,
    },
    (
        "job_id",
        "transcript_id",
        "status",
        "poll_after_s",
        "eta_hint",
        "cold_build_warning",
        "recommended_citation",
    ),
)

GET_TOLERANCE_LANDSCAPE_SCHEMA = output_schema(
    {
        "transcript_id": STR,
        "gene_name": STR_NULL,
        "protein_ac": STR_NULL,
        "refseq_ids": STR_ARRAY,
        "domains": {"type": "array", "items": {"$ref": "#/$defs/d"}},
        "positional_annotation": {"type": "array", "items": {"$ref": "#/$defs/o"}},
        "pagination": {"$ref": "#/$defs/p"},
        "status": {"const": "processing"},
        "poll_after_s": NUM,
        "cold_build_warning": STR,
        **_CITATION,
        **_CAVEAT,
    },
    ("transcript_id", "recommended_citation"),
    constraint={
        "oneOf": [
            {"required": ["status", "poll_after_s", "cold_build_warning"]},
            {"required": ["pagination"]},
        ]
    },
    defs={
        "d": DOMAIN,
        "p": PAGINATION,
        "o": POSITION,
        "q": POSITION_DOMAIN,
        "c": CLINVAR_VARIANT,
    },
)

GET_POSITION_TOLERANCE_SCHEMA = output_schema(
    {
        "transcript_id": STR,
        "cdna_pos": STR,
        "chr": STR,
        "chr_positions": STR,
        "exon_numbers": STR,
        "protein_pos": INT,
        "ref_aa": STR,
        "ref_aa_triplet": STR,
        "ref_codon": STR,
        "strand": STR,
        "sw_dn_ds": NUM_NULL,
        "sw_coverage": NUM,
        "sw_size": INT,
        "domains": {
            "type": "object",
            "additionalProperties": {"$ref": "#/$defs/dm"},
        },
        "variant_evidence": {"$ref": "#/$defs/e"},
        **_CITATION,
    },
    ("transcript_id", "protein_pos", "variant_evidence", "recommended_citation"),
    defs={"dm": DOMAIN_MEMBERSHIP, **EVIDENCE_DEFS},
)

GET_VARIANT_COUNTS_SCHEMA = output_schema(
    {
        "transcript_id": STR,
        "source": {"enum": ["both", "gnomad", "clinvar"]},
        "positions": {
            "type": "array",
            "items": closed(
                {
                    "protein_pos": INT,
                    "ref_aa": STR,
                    "sw_dn_ds": NUM_NULL,
                    "variant_evidence": {"$ref": "#/$defs/e"},
                    "clinvar_variants": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/c"},
                    },
                },
                ("protein_pos", "ref_aa", "sw_dn_ds", "variant_evidence"),
            ),
        },
        "pagination": {"$ref": "#/$defs/p"},
        **_CITATION,
        **_CAVEAT,
    },
    ("transcript_id", "source", "positions", "pagination", "recommended_citation"),
    defs={"p": PAGINATION, "c": CLINVAR_VARIANT, **EVIDENCE_DEFS},
)

COMPARE_POSITIONS_SCHEMA = output_schema(
    {
        "transcript_id": STR,
        "comparison": {
            "type": "array",
            "items": {
                "oneOf": [
                    closed(
                        {
                            "protein_pos": INT,
                            "ref_aa": STR,
                            "sw_dn_ds": NUM_NULL,
                            "domain_ids": STR_ARRAY,
                            "variant_evidence": {"$ref": "#/$defs/e"},
                        },
                        (
                            "protein_pos",
                            "ref_aa",
                            "sw_dn_ds",
                            "domain_ids",
                            "variant_evidence",
                        ),
                    ),
                    closed({"protein_pos": INT, "error": STR}, ("protein_pos", "error")),
                ]
            },
        },
        **_CITATION,
        **_CAVEAT,
    },
    ("transcript_id", "comparison", "recommended_citation"),
    defs=EVIDENCE_DEFS,
)

GET_PROTEIN_DOMAINS_SCHEMA = output_schema(
    {
        "transcript_id": STR,
        "gene_name": STR_NULL,
        "domains": {"type": "array", "items": {"$ref": "#/$defs/d"}},
        **_CITATION,
    },
    ("transcript_id", "domains", "recommended_citation"),
    defs={"d": DOMAIN},
)

GET_META_DOMAIN_SCHEMA = output_schema(
    {
        "transcript_id": STR,
        "protein_position": INT,
        "requested_domains": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": INT},
        },
        "meta_domains": {
            "type": "object",
            "additionalProperties": {"$ref": "#/$defs/m"},
        },
        **_CITATION,
        **_CAVEAT,
    },
    ("transcript_id", "protein_position", "meta_domains", "recommended_citation"),
    defs={
        "p": PAGINATION,
        "v": META_VARIANT_COMMON,
        "n": NORMAL_META_VARIANT,
        "a": PATHOGENIC_META_VARIANT,
        "m": META_DOMAIN,
    },
)

SUMMARIZE_INTOLERANT_REGIONS_SCHEMA = output_schema(
    {
        "transcript_id": STR,
        "gene_name": STR_NULL,
        "threshold": NUM,
        "min_run": INT,
        "top_n": INT,
        "regions": {"type": "array", "items": {"$ref": "#/$defs/i"}},
        **_CITATION,
        **_CAVEAT,
    },
    (
        "transcript_id",
        "threshold",
        "min_run",
        "top_n",
        "recommended_citation",
    ),
    defs={"i": INTOLERANT_REGION, **EVIDENCE_DEFS},
)
