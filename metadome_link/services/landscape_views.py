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

from metadome_link.constants import DATA_CURRENCY_CAVEAT, DEFAULT_PAGE_LIMIT
from metadome_link.exceptions import InvalidInputError
from metadome_link.services.citation import recommended_citation
from metadome_link.services.landscape import (
    domains_for_position,
    intolerant_runs,
    position_to_entry,
    slice_positions,
    variant_counts_for,
)
from metadome_link.services.pagination import paginate
from metadome_link.services.shaping import shape_record


def get_position_view(
    landscape: dict[str, Any], transcript_id: str, position: int, *, response_mode: str
) -> dict[str, Any]:
    """Return one residue's tolerance + domain + variant-count context."""
    entry = position_to_entry(landscape, position)
    payload = dict(entry)
    payload["transcript_id"] = transcript_id
    payload["counts"] = variant_counts_for(entry, "both")
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
    """Return per-position gnomAD/ClinVar counts (filtered by ``source``)."""
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
            "counts": variant_counts_for(entry, source),
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
            comparison.append({"protein_pos": pos, "error": exc.message})
            continue
        comparison.append(
            {
                "protein_pos": entry.get("protein_pos"),
                "ref_aa": entry.get("ref_aa"),
                "sw_dn_ds": entry.get("sw_dn_ds"),
                "domain_ids": sorted(_domain_ids(entry)),
                "counts": variant_counts_for(entry, "both"),
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
        gnomad_total, clinvar_total = _region_counts(landscape, run["start"], run["stop"])
        regions.append(
            {
                **run,
                "domains": overlapping,
                "gnomad_variant_count": gnomad_total,
                "clinvar_variant_count": clinvar_total,
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


def _region_counts(landscape: dict[str, Any], start: int, stop: int) -> tuple[int, int]:
    """Sum gnomAD + ClinVar variant counts across the residues of a region."""
    gnomad_total = 0
    clinvar_total = 0
    for entry in slice_positions(landscape, start, stop):
        counts = variant_counts_for(entry, "both")
        gnomad_total += int(counts.get("gnomad", {}).get("variant_count", 0))
        clinvar_total += int(counts.get("clinvar", {}).get("variant_count", 0))
    return gnomad_total, clinvar_total


def _clinvar_row(variant: dict[str, Any]) -> dict[str, Any]:
    """Project a ``/result/`` ClinVar entry + add the NCBI variation URL."""
    row = dict(variant)
    cid = variant.get("clinvar_ID")
    if isinstance(cid, str) and cid:
        row["url"] = f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{cid}/"
    return row
