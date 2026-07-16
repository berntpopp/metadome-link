"""Read-only "landscape view" assembly over a completed MetaDome landscape.

These module-level functions are the bodies of :class:`MetaDomeService`'s
read-only per-landscape operations (``get_position``, ``get_variant_counts``,
``compare_positions``, ``get_domains``, ``get_meta_domain``,
``summarize_intolerant_regions``). Each takes an **already-built** landscape dict
(fetched by the service via its cache / ``_require_landscape``) plus the request
parameters, and returns the plain result dict — never a ``success``/``_meta``
envelope (that is the MCP plane's job) and always carrying
``recommended_citation``.

They are deliberately I/O-free; the one operation that needs the client
(``get_meta_domain``'s meta-domain annotation fetch) is given the already-fetched
``raw`` annotation dict so the await stays in the orchestration layer. Splitting
the view assembly out of :mod:`metadome_link.services.metadome_service` keeps both
modules focused and within the per-file line budget. The lower-level pure helpers
(slicing, position lookup, variant counts, intolerant runs) live in
:mod:`metadome_link.services.landscape`.
"""

from __future__ import annotations

from typing import Any

from metadome_link.constants import (
    DATA_CURRENCY_CAVEAT,
    DEFAULT_PAGE_LIMIT,
    META_DOMAIN_HOMOLOG_AGGREGATE_PROVENANCE,
    RESIDUE_GNOMAD_UNAVAILABLE_REASON,
)
from metadome_link.exceptions import InvalidInputError
from metadome_link.mcp._sanitize import sanitize_message
from metadome_link.services.citation import recommended_citation
from metadome_link.services.landscape import (
    domains_for_position,
    has_meta_domain_homolog_aggregate,
    intolerant_runs,
    position_to_entry,
    slice_positions,
    variant_evidence_for,
)
from metadome_link.services.pagination import paginate
from metadome_link.services.shaping import shape_record


def get_position_view(
    landscape: dict[str, Any], transcript_id: str, position: int, *, response_mode: str
) -> dict[str, Any]:
    """Return one residue's tolerance + explicitly-scoped variant evidence."""
    entry = position_to_entry(landscape, position)
    payload = dict(entry)
    payload["domains"] = _position_domain_memberships(entry)
    payload.pop("ClinVar", None)
    payload["transcript_id"] = transcript_id
    payload["variant_evidence"] = variant_evidence_for(entry, "both")
    payload["recommended_citation"] = recommended_citation(
        transcript_id=transcript_id, gene_name=landscape.get("gene_name")
    )
    return shape_record(payload, response_mode)


def get_variant_counts_view(
    landscape: dict[str, Any],
    transcript_id: str,
    *,
    position: int | None = None,
    position_start: int | None = None,
    position_stop: int | None = None,
    source: str = "both",
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
    response_mode: str,
) -> dict[str, Any]:
    """Return explicitly-scoped residue and homolog evidence (filtered by ``source``)."""
    if position is not None:
        entries = [position_to_entry(landscape, position)]
    elif position_start is not None and position_stop is not None:
        entries = slice_positions(landscape, position_start, position_stop)
    else:
        raw = landscape.get("positional_annotation")
        entries = raw if isinstance(raw, list) else []

    rows: list[dict[str, Any]] = []
    for entry in entries:
        row: dict[str, Any] = {
            "protein_pos": entry.get("protein_pos"),
            "ref_aa": entry.get("ref_aa"),
            "sw_dn_ds": entry.get("sw_dn_ds"),
            "variant_evidence": variant_evidence_for(entry, source),
        }
        if source in ("both", "clinvar"):
            clinvar = entry.get("ClinVar")
            if isinstance(clinvar, list) and clinvar:
                row["clinvar_variants"] = [_clinvar_row(v) for v in clinvar]
        rows.append(row)

    # A single explicit position is returned whole (no pagination cap).
    page_limit = len(rows) or 1 if position is not None else limit
    page_offset = 0 if position is not None else offset
    page, block = paginate(rows, limit=page_limit, offset=page_offset)
    payload: dict[str, Any] = {
        "transcript_id": transcript_id,
        "source": source,
        "positions": page,
        "pagination": block,
        "data_currency_caveat": DATA_CURRENCY_CAVEAT,
        "recommended_citation": recommended_citation(
            transcript_id=transcript_id, gene_name=landscape.get("gene_name")
        ),
    }
    return shape_record(payload, response_mode)


def compare_positions_view(
    landscape: dict[str, Any], transcript_id: str, positions: list[int], *, response_mode: str
) -> dict[str, Any]:
    """Return a side-by-side tolerance table for a batch of positions."""
    comparison: list[dict[str, Any]] = []
    for pos in positions:
        try:
            entry = position_to_entry(landscape, pos)
        except InvalidInputError as exc:
            # This per-item ``error`` rides in an OTHERWISE-SUCCESSFUL batch response
            # (the tool "succeeded"), so it bypasses the MCP error envelope's
            # sanitation. Strip forbidden code points here at the row builder.
            comparison.append({"protein_pos": pos, "error": sanitize_message(exc.message)})
            continue
        comparison.append(
            {
                "protein_pos": entry.get("protein_pos"),
                "ref_aa": entry.get("ref_aa"),
                "sw_dn_ds": entry.get("sw_dn_ds"),
                "domain_ids": sorted(_domain_ids(entry)),
                "variant_evidence": variant_evidence_for(entry, "both"),
            }
        )
    payload: dict[str, Any] = {
        "transcript_id": transcript_id,
        "comparison": comparison,
        "data_currency_caveat": DATA_CURRENCY_CAVEAT,
        "recommended_citation": recommended_citation(
            transcript_id=transcript_id, gene_name=landscape.get("gene_name")
        ),
    }
    return shape_record(payload, response_mode)


def get_domains_view(
    landscape: dict[str, Any], transcript_id: str, *, response_mode: str
) -> dict[str, Any]:
    """Return the landscape's top-level Pfam ``domains[]``."""
    payload: dict[str, Any] = {
        "transcript_id": transcript_id,
        "gene_name": landscape.get("gene_name"),
        "domains": landscape.get("domains", []),
        "recommended_citation": recommended_citation(
            transcript_id=transcript_id, gene_name=landscape.get("gene_name")
        ),
    }
    return shape_record(payload, response_mode)


def resolve_meta_domain_request(
    landscape: dict[str, Any], position: int, domains: dict[str, list[int]] | None
) -> dict[str, list[int]]:
    """Resolve the ``requested_domains`` map for a meta-domain lookup.

    When ``domains`` is given it is used verbatim; otherwise it is derived from
    the cached residue's ``domains`` map (empty when the residue has no usable
    meta-domain mapping). Validates ``position`` is in range either way.
    """
    return domains if domains else domains_for_position(landscape, position)


def get_meta_domain_view(
    landscape: dict[str, Any],
    transcript_id: str,
    position: int,
    requested: dict[str, list[int]],
    raw: dict[str, Any],
    *,
    limit: int,
    offset: int,
    response_mode: str,
) -> dict[str, Any]:
    """Shape the homologous (meta-domain) variant detail for a residue.

    ``requested`` is the resolved ``requested_domains`` map and ``raw`` is the
    already-fetched ``get_metadomain_annotation`` response (empty when no domains
    were requested), so this function stays I/O-free.
    """
    meta_domains: dict[str, Any] = {}
    for pfam_id, block in raw.items():
        if not isinstance(block, dict):
            continue
        normal = block.get("normal_variants")
        patho = block.get("pathogenic_variants")
        normal_list = normal if isinstance(normal, list) else []
        patho_list = patho if isinstance(patho, list) else []
        normal_page, normal_block = paginate(normal_list, limit=limit, offset=offset)
        patho_page, patho_block = paginate(patho_list, limit=limit, offset=offset)
        meta_domains[pfam_id] = {
            "alignment_depth": block.get("alignment_depth"),
            "normal_variants": normal_page,
            "pathogenic_variants": patho_page,
            "pagination": {
                "normal_variants": normal_block,
                "pathogenic_variants": patho_block,
            },
        }

    payload: dict[str, Any] = {
        "transcript_id": transcript_id,
        "protein_position": position,
        "requested_domains": requested,
        "meta_domains": meta_domains,
        "data_currency_caveat": DATA_CURRENCY_CAVEAT,
        "recommended_citation": recommended_citation(
            transcript_id=transcript_id, gene_name=landscape.get("gene_name")
        ),
    }
    return shape_record(payload, response_mode)


def summarize_intolerant_regions_view(
    landscape: dict[str, Any],
    transcript_id: str,
    *,
    threshold: float = 0.5,
    min_run: int = 3,
    top_n: int = 15,
    response_mode: str,
) -> dict[str, Any]:
    """Summarise the most intolerant contiguous regions of the landscape."""
    runs = intolerant_runs(landscape, threshold, min_run, top_n)
    domains = landscape.get("domains")
    domain_spans = domains if isinstance(domains, list) else []

    regions: list[dict[str, Any]] = []
    for run in runs:
        overlapping = sorted(_overlapping_domains(domain_spans, run["start"], run["stop"]))
        regions.append(
            {
                **run,
                "domains": overlapping,
                "variant_evidence": _region_variant_evidence(landscape, run["start"], run["stop"]),
            }
        )
    payload: dict[str, Any] = {
        "transcript_id": transcript_id,
        "gene_name": landscape.get("gene_name"),
        "threshold": threshold,
        "min_run": min_run,
        "top_n": top_n,
        "regions": regions,
        "data_currency_caveat": DATA_CURRENCY_CAVEAT,
        "recommended_citation": recommended_citation(
            transcript_id=transcript_id, gene_name=landscape.get("gene_name")
        ),
    }
    return shape_record(payload, response_mode)


def _domain_ids(entry: dict[str, Any]) -> set[str]:
    """Return the set of Pfam ids covering a residue (from its ``domains`` map)."""
    domains = entry.get("domains")
    if isinstance(domains, dict):
        return {str(k) for k in domains}
    return set()


def _position_domain_memberships(entry: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """Keep domain membership while removing raw, unscoped upstream count fields."""
    domains = entry.get("domains")
    if not isinstance(domains, dict):
        return {}
    return {
        str(pfam_id): {
            "meta_domain_homolog_aggregate_available": has_meta_domain_homolog_aggregate(mapping)
        }
        for pfam_id, mapping in domains.items()
    }


def _overlapping_domains(domain_spans: list[dict[str, Any]], start: int, stop: int) -> set[str]:
    """Return Pfam ids whose ``[start, stop]`` span overlaps ``[start, stop]``."""
    out: set[str] = set()
    for domain in domain_spans:
        d_start = domain.get("start")
        d_stop = domain.get("stop")
        d_id = domain.get("ID")
        if (
            isinstance(d_start, int)
            and isinstance(d_stop, int)
            and isinstance(d_id, str)
            and d_start <= stop
            and d_stop >= start
        ):
            out.add(d_id)
    return out


def _region_variant_evidence(landscape: dict[str, Any], start: int, stop: int) -> dict[str, Any]:
    """Summarise true ClinVar and separately-labelled homolog evidence for a region."""
    gnomad_total = 0
    gnomad_missense = 0
    residue_clinvar_total = 0
    residue_clinvar_missense = 0
    homolog_clinvar_total = 0
    homolog_clinvar_missense = 0
    any_homolog_aggregate = False
    for entry in slice_positions(landscape, start, stop):
        evidence = variant_evidence_for(entry, "both")
        residue_clinvar = evidence["residue_level"].get("clinvar", {})
        residue_clinvar_total += int(residue_clinvar.get("variant_count", 0))
        residue_clinvar_missense += int(residue_clinvar.get("missense_variant_count", 0))
        homologs = evidence["meta_domain_homolog_aggregate"]
        if homologs["available"]:
            any_homolog_aggregate = True
            gnomad = homologs.get("gnomad", {})
            clinvar = homologs.get("clinvar", {})
            gnomad_total += int(gnomad.get("variant_count", 0))
            gnomad_missense += int(gnomad.get("missense_variant_count", 0))
            # This is intentionally distinct from ``residue_clinvar`` above.
            homolog_clinvar_total += int(clinvar.get("variant_count", 0))
            homolog_clinvar_missense += int(clinvar.get("missense_variant_count", 0))

    homolog_aggregate: dict[str, Any] = {
        "available": any_homolog_aggregate,
        "provenance": META_DOMAIN_HOMOLOG_AGGREGATE_PROVENANCE,
        "scope": "sum of per-residue aligned-homolog aggregates; not a unique-variant count",
    }
    if any_homolog_aggregate:
        homolog_aggregate["gnomad"] = {
            "variant_count": gnomad_total,
            "missense_variant_count": gnomad_missense,
        }
        homolog_aggregate["clinvar"] = {
            "variant_count": homolog_clinvar_total,
            "missense_variant_count": homolog_clinvar_missense,
        }
    else:
        homolog_aggregate["reason"] = "No Pfam meta-domain maps any residue in this region."

    return {
        "residue_level": {
            "gnomad": {"available": False, "reason": RESIDUE_GNOMAD_UNAVAILABLE_REASON},
            "clinvar": {
                "available": True,
                "variant_count": residue_clinvar_total,
                "missense_variant_count": residue_clinvar_missense,
                "provenance": "Sum of MetaDome's per-residue ClinVar annotations in this region.",
            },
        },
        "meta_domain_homolog_aggregate": homolog_aggregate,
    }


def _clinvar_row(variant: dict[str, Any]) -> dict[str, Any]:
    """Project a ``/result/`` ClinVar entry + add the NCBI variation URL."""
    row = dict(variant)
    cid = variant.get("clinvar_ID")
    if isinstance(cid, str) and cid:
        row["url"] = f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{cid}/"
    return row
