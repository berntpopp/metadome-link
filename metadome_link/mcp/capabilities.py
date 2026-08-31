"""Capabilities payload and metadome:// discovery resources."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

from metadome_link import __version__
from metadome_link.buildinfo import build_info
from metadome_link.constants import (
    DEFAULT_DATA_PROFILE,
    DEFAULT_PAGE_LIMIT,
    DEFAULT_RESPONSE_MODE,
    MAX_BATCH_POSITIONS,
    MAX_PAGE_LIMIT,
    METADOME_LICENSE,
    RECOMMENDED_CITATION,
    RESEARCH_USE_NOTICE,
    RESPONSE_MODES,
    data_profile,
)
from metadome_link.mcp.resources import METADOME_REFERENCE_NOTES, METADOME_USAGE_NOTES

if TYPE_CHECKING:
    pass

#: Error taxonomy surfaced by every tool (see metadome_link.mcp.envelope).
ERROR_CODES: list[str] = [
    "invalid_input",
    "not_found",
    "ambiguous_query",
    "upstream_unavailable",
    "rate_limited",
    "internal",
]

#: Frozen tool surface (11 tools). TOOLS must equal the registered tool set.
#: Order is canonical: discovery → transcripts → landscape → positions → domains → analysis.
TOOLS: list[str] = [
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

#: Keys extracted for the summary detail level.
_SUMMARY_KEYS: tuple[str, ...] = (
    "server",
    "server_version",
    "build",
    "capabilities_version",
    "genome_build",
    "data_version",
    "data_versions",
    "data_source",
    "research_use_only",
    "research_use_notice",
    "data_currency_caveat",
    "recommended_citation",
    "license",
    "tools",
    "tool_count",
    "response_modes",
    "default_response_mode",
    "recommended_workflows",
    "error_codes",
    "limits",
    "read_only",
)

#: ``capabilities_version`` is a content hash of the discovery CONTRACT, cached per
#: MetaDome data version so the per-call envelope echo never re-derives it.
#: ``build`` (per-deploy git sha / timestamp) and the self-hash are excluded so
#: unrelated redeploys do not churn the value — a warm client diffs it to skip
#: re-fetching.
_HASH_EXCLUDE: frozenset[str] = frozenset({"build", "capabilities_version"})
_VERSION_CACHE: dict[str, str] = {}


def _hash_contract(payload: dict[str, Any]) -> str:
    """Deterministic short hash of the discovery contract (volatile keys removed)."""
    contract = {k: v for k, v in payload.items() if k not in _HASH_EXCLUDE}
    blob = json.dumps(contract, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _active_profile() -> tuple[dict[str, str], str, str]:
    """Resolve runtime provenance, falling back to the default before startup."""
    try:
        from metadome_link.mcp.service_adapters import get_metadome_service

        service = get_metadome_service()
        return service.data_versions, service.data_version, service.genome_build
    except Exception:
        return (
            dict(DEFAULT_DATA_PROFILE.data_versions),
            DEFAULT_DATA_PROFILE.data_version,
            DEFAULT_DATA_PROFILE.genome_build,
        )


def capabilities_version(
    *, data_versions: dict[str, str] | None = None, data_version: str | None = None
) -> str:
    """Cached content hash of the discovery contract (echoed in every ``_meta``)."""
    versions, resolved_version, _ = _active_profile()
    if data_versions is not None:
        versions = data_versions
    if data_version is not None:
        resolved_version = data_version
    key = resolved_version
    cached = _VERSION_CACHE.get(key)
    if cached is None:
        cached = build_capabilities(data_versions=versions, data_version=resolved_version)[
            "capabilities_version"
        ]
        _VERSION_CACHE[key] = cached
    return cached


def build_capabilities(
    *,
    data_versions: dict[str, str] | None = None,
    data_version: str | None = None,
    genome_build: str | None = None,
) -> dict[str, Any]:
    """Return the discovery surface describing this server."""
    active_versions, _, active_build = _active_profile()
    if genome_build is not None and data_versions is None:
        profile = data_profile(genome_build)
        active_versions = dict(profile.data_versions)
    versions = dict(data_versions if data_versions is not None else active_versions)
    resolved_build = genome_build or versions.get("assembly", active_build)
    if versions.get("assembly") != resolved_build:
        raise ValueError("data_versions assembly and genome_build must match")
    profile = data_profile(resolved_build)
    if data_version is not None and data_version != profile.data_version:
        raise ValueError("data_version and genome_build must identify the same profile")
    version = data_version if data_version is not None else profile.data_version
    payload: dict[str, Any] = {
        "server": "metadome-link",
        "server_version": __version__,
        "build": build_info(),
        "data_versions": versions,
        "data_source": "MetaDome (www.metadome.app/metadome)",
        "research_use_only": True,
        "research_use_notice": RESEARCH_USE_NOTICE,
        "data_currency_caveat": _caveat_for_versions(versions),
        "recommended_citation": RECOMMENDED_CITATION,
        "license": METADOME_LICENSE,
        "tools": TOOLS,
        "tool_count": len(TOOLS),
        "response_modes": list(RESPONSE_MODES),
        "default_response_mode": DEFAULT_RESPONSE_MODE,
        "recommended_workflows": [
            (
                "resolve_transcript(query) → request_tolerance_landscape(transcript_id) "
                "→ get_tolerance_landscape(transcript_id) → get_position_tolerance / "
                "get_variant_counts / get_protein_domains / get_meta_domain / "
                "summarize_intolerant_regions / compare_positions"
            ),
            "gene symbol → resolve_transcript → canonical transcript_id",
            "ENST id → resolve_transcript (validates version suffix) → canonical",
            "transcript_id → request_tolerance_landscape → status:'ready'|'processing'",
            "transcript_id → get_tolerance_landscape → paginated positional_annotation",
            "transcript_id + position → get_position_tolerance → sw_dn_ds, domains",
            "transcript_id + position → get_meta_domain → homologous-domain variants",
            "transcript_id → summarize_intolerant_regions → ranked constrained windows",
            "transcript_id + positions[] → compare_positions → side-by-side table",
        ],
        "error_codes": ERROR_CODES,
        "limits": {
            "max_batch_positions": MAX_BATCH_POSITIONS,
            "default_page_limit": DEFAULT_PAGE_LIMIT,
            "max_page_limit": MAX_PAGE_LIMIT,
        },
        "read_only": True,
        "async_model": (
            "MetaDome computes tolerance landscapes asynchronously (Celery). Popular "
            "transcripts (e.g. TP53) are pre-built and return status='ready' immediately; "
            "a cold build can take up to ~1 hour. Use request_tolerance_landscape to "
            "submit (idempotent), then poll get_tolerance_landscape. "
            "status:'processing' is a first-class success state, not an error."
        ),
        "score_semantics": (
            "sw_dn_ds is a background-corrected missense/synonymous ratio over a "
            "±10-residue sliding window (1-based positions). Lower values indicate "
            "more constrained/intolerant positions. Null sw_dn_ds is valid near termini "
            "where the sliding window is incomplete."
        ),
        "provenance_policy": (
            "Static provenance (research-use restriction, data-currency caveat, "
            "citation, MetaDome data version) is declared here and applies to ALL tool "
            "outputs; _meta.data_versions echoes it per call. Per-residue gnomAD counts "
            "are unavailable; Pfam homolog aggregates are explicitly scoped and may span genes."
        ),
        "per_call_meta": [
            "tool",
            "request_id",
            "elapsed_ms",
            "capabilities_version",
            "next_commands",
            "data_versions",
        ],
        "per_call_meta_semantics": (
            "_meta verbosity is tiered by response_mode: minimal preserves the core answer "
            "with trace/provenance fields; compact (default) adds next_commands and "
            "capabilities_version; standard/full add elapsed_ms. "
            "data_versions is always present."
        ),
        "notes": METADOME_REFERENCE_NOTES,
    }
    payload["data_version"] = version
    payload["genome_build"] = resolved_build
    payload["capabilities_version"] = _hash_contract(payload)
    return payload


def _caveat_for_versions(versions: dict[str, str]) -> str:
    """Render a truthful build-specific currency warning from profile values."""
    assembly = versions.get("assembly", "unknown")
    components = ", ".join(
        f"{label} {versions[key]}"
        for label, key in (
            ("GENCODE", "gencode"),
            ("UniProt", "uniprot"),
            ("Pfam", "pfam"),
            ("gnomAD", "gnomad"),
            ("ClinVar", "clinvar"),
        )
        if key in versions
    )
    return (
        f"MetaDome data use {assembly} ({components}); MetaDome does not provide true "
        "per-residue gnomAD counts. Its Pfam meta-domain aggregates can include other "
        "genes; use live gnomAD/ClinVar for current evidence."
    )


def register_capability_resources(mcp: FastMCP) -> None:
    """Register the metadome:// resource family on a FastMCP instance."""

    @mcp.resource("metadome://capabilities", mime_type="application/json")
    def capabilities() -> str:
        return json.dumps(build_capabilities(), indent=2)

    @mcp.resource("metadome://tools", mime_type="application/json")
    def tools_overview() -> str:
        return json.dumps(
            {"server": "metadome-link", "tools": TOOLS, "tool_count": len(TOOLS)},
            indent=2,
        )

    @mcp.resource("metadome://usage", mime_type="text/plain")
    def usage() -> str:
        return METADOME_USAGE_NOTES

    @mcp.resource("metadome://reference", mime_type="text/plain")
    def reference() -> str:
        return METADOME_REFERENCE_NOTES

    @mcp.resource("metadome://research-use", mime_type="text/plain")
    def research_use() -> str:
        return RESEARCH_USE_NOTICE

    @mcp.resource("metadome://citation", mime_type="text/plain")
    def citation() -> str:
        return RECOMMENDED_CITATION
