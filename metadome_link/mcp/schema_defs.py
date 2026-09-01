"""Reusable closed JSON-Schema fragments for MetaDome tool outputs."""

from __future__ import annotations

import json
import re
from typing import Any

STR = {"type": "string"}
STR_NULL = {"type": ["string", "null"]}
INT = {"type": "integer"}
INT_NULL = {"type": ["integer", "null"]}
NUM = {"type": "number"}
NUM_NULL = {"type": ["number", "null"]}
BOOL = {"type": "boolean"}
STR_ARRAY = {"type": "array", "items": STR}


def closed(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a compact closed object schema with an explicit required set."""
    groups: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for name, value in properties.items():
        identity = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if identity not in groups:
            groups[identity] = (value, [])
        groups[identity][1].append(name)
    patterns = {}
    for value, names in groups.values():
        joined = "|".join(re.escape(name) for name in names)
        patterns[f"^{joined}$" if len(names) == 1 else f"^({joined})$"] = value
    schema: dict[str, Any] = {
        "type": "object",
        "patternProperties": patterns,
        "additionalProperties": False,
    }
    if required and set(required) == set(properties):
        schema["minProperties"] = len(required)
    elif required:
        schema["required"] = list(required)
    return schema


DATA_VERSIONS = {
    "type": "object",
    "required": ["assembly", "metadome_app"],
    "additionalProperties": {"type": "string"},
}

META = closed(
    {
        "tool": STR,
        "request_id": STR,
        "data_versions": {"$ref": "#/$defs/V"},
        "unsafe_for_clinical_use": {"const": True},
        "elapsed_ms": INT,
        "capabilities_version": STR,
        "next_commands": {"type": "array", "items": {"type": "object"}},
    },
    ("tool", "request_id", "data_versions", "unsafe_for_clinical_use"),
)

PAGINATION = closed(
    {
        "total": INT,
        "returned": INT,
        "limit": INT,
        "offset": INT,
        "truncated": BOOL,
        "next_offset": INT_NULL,
    },
    ("total", "returned", "limit", "offset", "truncated", "next_offset"),
)
BUILD = closed(
    {"version": STR, "git_sha": STR, "built_at": STR_NULL},
    ("version", "git_sha", "built_at"),
)
LIMITS = closed(
    {"max_batch_positions": INT, "default_page_limit": INT, "max_page_limit": INT},
    ("max_batch_positions", "default_page_limit", "max_page_limit"),
)
TRANSCRIPT = closed(
    {
        "gencode_id": STR,
        "aa_length": INT,
        "has_protein_data": BOOL,
        "mane_transcript_type": STR,
        "refseq_ids": STR_ARRAY,
        "canonical": BOOL,
    },
    (
        "gencode_id",
        "aa_length",
        "has_protein_data",
        "mane_transcript_type",
        "refseq_ids",
        "canonical",
    ),
)
TOOL_MODES = closed(
    {"read_only": STR_ARRAY, "compute_orchestration": STR_ARRAY},
    ("read_only", "compute_orchestration"),
)

TALLY = closed({"requests": INT, "errors": INT}, ("requests", "errors"))
LATENCY = closed(
    dict.fromkeys(("p50", "p95", "p99", "max", "sampled"), INT),
    ("p50", "p95", "p99", "max", "sampled"),
)
METRICS = closed(
    {
        "requests": INT,
        "errors": INT,
        "error_rate": NUM_NULL,
        "latency_ms": {"$ref": "#/$defs/y"},
        "per_tool": {"type": "object", "additionalProperties": {"$ref": "#/$defs/z"}},
    },
    ("requests", "errors", "error_rate", "latency_ms", "per_tool"),
)

DOMAIN = closed(
    {
        "ID": STR,
        "Name": STR,
        "start": INT,
        "stop": INT,
        "metadomain": BOOL,
        "meta_domain_alignment_depth": INT,
    },
    ("ID", "Name", "start", "stop", "metadomain", "meta_domain_alignment_depth"),
)
COUNT_BY_SIGNIFICANCE = {
    "type": "object",
    "additionalProperties": NUM,
}
POSITION_DOMAIN = closed(
    {
        "normal_variant_count": NUM,
        "normal_missense_variant_count": NUM,
        "pathogenic_variant_count": NUM,
        "pathogenic_missense_variant_count": NUM,
        "consensus_pos": {"type": "array", "items": INT},
        "pathogenic_variant_count_per_clinsig": COUNT_BY_SIGNIFICANCE,
        "pathogenic_missense_variant_count_per_clinsig": COUNT_BY_SIGNIFICANCE,
    },
    (
        "normal_variant_count",
        "normal_missense_variant_count",
        "pathogenic_variant_count",
        "pathogenic_missense_variant_count",
        "consensus_pos",
    ),
)
CLINVAR_VARIANT = closed(
    {
        "alt": STR,
        "alt_aa": STR,
        "alt_aa_triplet": STR,
        "alt_codon": STR,
        "clinvar_ID": STR,
        "clinvar_clinsig": STR,
        "pos": INT,
        "ref": STR,
        "type": STR,
        "url": STR,
    },
    ("alt", "alt_aa", "alt_aa_triplet", "alt_codon", "clinvar_ID", "pos", "ref", "type"),
)
POSITION = closed(
    {
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
            "additionalProperties": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/q"}]},
        },
        "ClinVar": {"type": "array", "items": {"$ref": "#/$defs/c"}},
    },
    (
        "cdna_pos",
        "chr",
        "chr_positions",
        "protein_pos",
        "ref_aa",
        "ref_aa_triplet",
        "ref_codon",
        "strand",
        "sw_dn_ds",
        "sw_coverage",
        "sw_size",
        "domains",
    ),
)
DOMAIN_MEMBERSHIP = closed(
    {"meta_domain_homolog_aggregate_available": BOOL},
    ("meta_domain_homolog_aggregate_available",),
)

COUNTS = closed(
    {"variant_count": INT, "missense_variant_count": INT},
    ("variant_count", "missense_variant_count"),
)
UNAVAILABLE = closed({"available": {"const": False}, "reason": STR}, ("available", "reason"))
AVAILABLE_CLINVAR = closed(
    {
        "available": {"const": True},
        "variant_count": INT,
        "missense_variant_count": INT,
        "provenance": STR,
    },
    ("available", "variant_count", "missense_variant_count", "provenance"),
)
RESIDUE_EVIDENCE = closed(
    {
        "gnomad": {"$ref": "#/$defs/u"},
        "clinvar": {"$ref": "#/$defs/a"},
    }
)
RESIDUE_EVIDENCE["minProperties"] = 1
HOMOLOG_EVIDENCE = closed(
    {
        "available": BOOL,
        "provenance": STR,
        "scope": STR,
        "reason": STR,
        "gnomad": {"$ref": "#/$defs/co"},
        "clinvar": {"$ref": "#/$defs/co"},
    },
    ("available", "provenance"),
)
VARIANT_EVIDENCE = closed(
    {
        "residue_level": {"$ref": "#/$defs/r"},
        "meta_domain_homolog_aggregate": {"$ref": "#/$defs/h"},
    },
    ("residue_level", "meta_domain_homolog_aggregate"),
)
EVIDENCE_DEFS = {
    "co": COUNTS,
    "u": UNAVAILABLE,
    "a": AVAILABLE_CLINVAR,
    "r": RESIDUE_EVIDENCE,
    "h": HOMOLOG_EVIDENCE,
    "e": VARIANT_EVIDENCE,
}

META_VARIANT_BASE = {
    "alt": STR,
    "alt_aa": STR,
    "alt_aa_triplet": STR,
    "alt_codon": STR,
    "cdna_pos": STR,
    "chr": STR,
    "chr_positions": STR,
    "exon_numbers": STR,
    "gene_name": STR,
    "pos": INT,
    "protein_pos": INT,
    "ref": STR,
    "ref_aa": STR,
    "ref_aa_triplet": STR,
    "ref_codon": STR,
    "strand": STR,
    "type": STR,
}
META_VARIANT_REQUIRED = tuple(key for key in META_VARIANT_BASE if key != "exon_numbers")
META_VARIANT_COMMON = closed(META_VARIANT_BASE, META_VARIANT_REQUIRED)
META_VARIANT_COMMON.pop("additionalProperties")
NORMAL_META_VARIANT = {
    "allOf": [
        {"$ref": "#/$defs/v"},
        {
            "type": "object",
            "patternProperties": {"^(allele_count|allele_number)$": NUM},
            "required": ["allele_count", "allele_number"],
        },
    ],
    "unevaluatedProperties": False,
}
PATHOGENIC_META_VARIANT = {
    "allOf": [
        {"$ref": "#/$defs/v"},
        {
            "type": "object",
            "patternProperties": {"^(clinvar_ID|clinvar_clinsig)$": STR},
            "required": ["clinvar_ID"],
        },
    ],
    "unevaluatedProperties": False,
}
META_DOMAIN = closed(
    {
        "alignment_depth": INT,
        "normal_variants": {"type": "array", "items": {"$ref": "#/$defs/n"}},
        "pathogenic_variants": {
            "type": "array",
            "items": {"$ref": "#/$defs/a"},
        },
        "pagination": closed(
            {
                "normal_variants": {"$ref": "#/$defs/p"},
                "pathogenic_variants": {"$ref": "#/$defs/p"},
            },
            ("normal_variants", "pathogenic_variants"),
        ),
    },
    ("alignment_depth", "normal_variants", "pathogenic_variants", "pagination"),
)

INTOLERANT_REGION = closed(
    {
        "start": INT,
        "stop": INT,
        "length": INT,
        "mean_sw_dn_ds": NUM,
        "min_sw_dn_ds": NUM,
        "domains": STR_ARRAY,
        "variant_evidence": {"$ref": "#/$defs/e"},
    },
    ("start", "stop", "length", "mean_sw_dn_ds", "min_sw_dn_ds", "domains", "variant_evidence"),
)

ERROR_CODE = {
    "enum": [
        "invalid_input",
        "not_found",
        "ambiguous_query",
        "upstream_unavailable",
        "rate_limited",
        "internal",
    ]
}
CANDIDATE = closed({"transcript_id": STR}, ("transcript_id",))
ERROR_PROPERTIES = {
    "success": {"const": False},
    "_meta": {"$ref": "#/$defs/M"},
    "error_code": ERROR_CODE,
    "message": STR,
    "retryable": BOOL,
    "recovery_action": STR,
    "field": STR,
    "hint": STR,
    "allowed_values": {"type": "array"},
    "candidates": {"type": "array", "items": {"$ref": "#/$defs/C"}},
}


def output_schema(
    properties: dict[str, Any],
    required: tuple[str, ...],
    *,
    constraint: dict[str, Any] | None = None,
    defs: dict[str, Any] | None = None,
    candidates: bool = False,
) -> dict[str, Any]:
    """Build a genuine two-branch, closed success/error output contract."""
    success_properties = {
        "success": {"const": True},
        "_meta": {"$ref": "#/$defs/M"},
        "dropped_summary": STR,
        **properties,
    }
    success = closed(success_properties, ("success", "_meta", *required))
    if constraint is not None:
        success.update(constraint)
    error_properties = dict(ERROR_PROPERTIES)
    if not candidates:
        error_properties.pop("candidates")
    error = closed(
        error_properties,
        ("success", "_meta", "error_code", "message", "retryable", "recovery_action"),
    )
    all_defs = {
        "V": DATA_VERSIONS,
        "M": META,
        **(defs or {}),
    }
    if candidates:
        all_defs["C"] = CANDIDATE
    return {
        "type": "object",
        "patternProperties": {".*": {}},
        "additionalProperties": False,
        "oneOf": [success, error],
        "$defs": all_defs,
    }
