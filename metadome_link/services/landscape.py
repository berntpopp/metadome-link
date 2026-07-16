"""Pure helpers over a completed MetaDome tolerance landscape.

A landscape is the normalized ``/result/`` dict: top-level ``transcript_id``,
``gene_name``, ``protein_ac``, ``refseq_ids``, ``domains[]`` and a
``positional_annotation[]`` of one entry per protein residue. Protein positions
(``protein_pos``) and Pfam ``consensus_pos`` are **1-based**; ``sw_dn_ds``
(lower = more intolerant/constrained) may be ``null``.

These helpers slice, look up, summarise and project a landscape without any I/O
so they are deterministic and unit-testable. They raise
:class:`~metadome_link.exceptions.InvalidInputError` on an out-of-range position.
"""

from __future__ import annotations

from typing import Any

from metadome_link.constants import (
    META_DOMAIN_HOMOLOG_AGGREGATE_PROVENANCE,
    RESIDUE_GNOMAD_UNAVAILABLE_REASON,
)
from metadome_link.exceptions import InvalidInputError

_HOMOLOG_COUNT_KEYS = (
    "normal_variant_count",
    "normal_missense_variant_count",
    "pathogenic_variant_count",
    "pathogenic_missense_variant_count",
)


def _positions(landscape: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ``positional_annotation`` list (empty if absent/malformed)."""
    entries = landscape.get("positional_annotation")
    if isinstance(entries, list):
        return [e for e in entries if isinstance(e, dict)]
    return []


def _max_position(landscape: dict[str, Any]) -> int:
    """Return the highest ``protein_pos`` present (the protein length bound).

    Prefers a top-level ``aa_length`` when present (the upstream guarantees
    ``len(positional_annotation) == aa_length``), else the maximum
    ``protein_pos`` observed in the entries.
    """
    aa_length = landscape.get("aa_length")
    if isinstance(aa_length, int) and aa_length > 0:
        return aa_length
    positions = [
        int(e["protein_pos"])
        for e in _positions(landscape)
        if isinstance(e.get("protein_pos"), int)
    ]
    return max(positions) if positions else 0


def position_to_entry(landscape: dict[str, Any], pos: int) -> dict[str, Any]:
    """Return the ``positional_annotation`` entry for 1-based residue *pos*.

    Looks up by the entry's ``protein_pos`` field (positions need not be
    contiguous in a trimmed/partial landscape), validating the request against
    the protein length first.

    Raises:
        InvalidInputError: If *pos* is < 1 or beyond the protein length, or if
            no entry exists for that position.
    """
    upper = _max_position(landscape)
    if pos < 1 or (upper and pos > upper):
        raise InvalidInputError(
            f"Position {pos} is out of range (protein has {upper} residues).",
            field="position",
            hint=f"Use a 1-based position in [1, {upper}].",
        )
    for entry in _positions(landscape):
        if entry.get("protein_pos") == pos:
            return entry
    raise InvalidInputError(
        f"No landscape entry for position {pos}.",
        field="position",
        hint=f"Use a 1-based position in [1, {upper}].",
    )


def slice_positions(landscape: dict[str, Any], start: int, stop: int) -> list[dict[str, Any]]:
    """Return entries whose ``protein_pos`` falls within ``[start, stop]`` (inclusive).

    The bounds are clamped lazily — entries outside the range are simply omitted;
    an empty result is valid (e.g. a range past the protein length).
    """
    lo, hi = (start, stop) if start <= stop else (stop, start)
    return [
        e
        for e in _positions(landscape)
        if isinstance(e.get("protein_pos"), int) and lo <= e["protein_pos"] <= hi
    ]


def domains_for_position(landscape: dict[str, Any], pos: int) -> dict[str, list[int]]:
    """Derive ``{PfamID: [consensus_pos, ...]}`` for the residue at *pos*.

    Reads the residue's ``domains`` map and keeps only Pfam entries that carry a
    non-empty ``consensus_pos`` list (a ``null`` value means in-domain but no
    meta-domain context at that position — skipped). Returns ``{}`` when the
    residue has no usable meta-domain mapping; this is the ``requested_domains``
    payload for a :meth:`MetaDomeClient.get_metadomain_annotation` call.

    Raises:
        InvalidInputError: If *pos* is out of range (via :func:`position_to_entry`).
    """
    entry = position_to_entry(landscape, pos)
    raw = entry.get("domains")
    out: dict[str, list[int]] = {}
    if not isinstance(raw, dict):
        return out
    for pfam_id, mapping in raw.items():
        if not isinstance(mapping, dict):
            continue
        consensus = mapping.get("consensus_pos")
        if isinstance(consensus, list) and consensus:
            out[str(pfam_id)] = [int(c) for c in consensus if isinstance(c, int)]
    return out


def has_meta_domain_homolog_aggregate(mapping: object) -> bool:
    """Whether a domain mapping carries at least one usable homolog-count field."""
    return isinstance(mapping, dict) and any(
        isinstance(mapping.get(key), int | float) for key in _HOMOLOG_COUNT_KEYS
    )


def variant_evidence_for(entry: dict[str, Any], source: str) -> dict[str, Any]:
    """Return explicitly-scoped residue and aligned-homolog variant evidence.

    MetaDome provides actual per-residue ``ClinVar`` annotations, but it does not
    expose true per-residue gnomAD observations.  Its domain ``normal_*`` and
    ``pathogenic_*`` fields are instead aggregates over aligned Pfam homologs.
    Keep those meanings structurally separate so consumers cannot treat a
    cross-gene aggregate as evidence for the requested transcript residue.
    """
    gnomad_total = 0
    gnomad_missense = 0
    patho_total = 0
    patho_missense = 0

    domains = entry.get("domains")
    mappings = (
        [mapping for mapping in domains.values() if has_meta_domain_homolog_aggregate(mapping)]
        if isinstance(domains, dict)
        else []
    )
    for mapping in mappings:
        gnomad_total += _as_int(mapping.get("normal_variant_count"))
        gnomad_missense += _as_int(mapping.get("normal_missense_variant_count"))
        patho_total += _as_int(mapping.get("pathogenic_variant_count"))
        patho_missense += _as_int(mapping.get("pathogenic_missense_variant_count"))

    clinvar_entries = entry.get("ClinVar")
    clinvar_here = clinvar_entries if isinstance(clinvar_entries, list) else []

    residue_level: dict[str, Any] = {}
    if source in ("both", "gnomad"):
        residue_level["gnomad"] = {
            "available": False,
            "reason": RESIDUE_GNOMAD_UNAVAILABLE_REASON,
        }
    if source in ("both", "clinvar"):
        residue_level["clinvar"] = {
            "available": True,
            "variant_count": len(clinvar_here),
            "missense_variant_count": sum(
                1
                for variant in clinvar_here
                if isinstance(variant, dict) and variant.get("type") == "missense"
            ),
            "provenance": "MetaDome's per-residue ClinVar annotation for this transcript.",
        }

    homolog_aggregate: dict[str, Any] = {
        "available": bool(mappings),
        "provenance": META_DOMAIN_HOMOLOG_AGGREGATE_PROVENANCE,
    }
    if homolog_aggregate["available"]:
        if source in ("both", "gnomad"):
            homolog_aggregate["gnomad"] = {
                "variant_count": gnomad_total,
                "missense_variant_count": gnomad_missense,
            }
        if source in ("both", "clinvar"):
            homolog_aggregate["clinvar"] = {
                "variant_count": patho_total,
                "missense_variant_count": patho_missense,
            }
    else:
        homolog_aggregate["reason"] = "No Pfam meta-domain maps this residue."

    return {
        "residue_level": residue_level,
        "meta_domain_homolog_aggregate": homolog_aggregate,
    }


def intolerant_runs(
    landscape: dict[str, Any],
    threshold: float,
    min_run: int,
    top_n: int,
) -> list[dict[str, Any]]:
    """Find the most intolerant contiguous residue runs (mean ``sw_dn_ds`` below *threshold*).

    A run is a maximal stretch of **consecutive** protein positions whose
    ``sw_dn_ds`` is non-null and strictly below *threshold*. Runs shorter than
    *min_run* are discarded. The survivors are ranked by mean ``sw_dn_ds``
    ascending (most constrained first) and the top *top_n* returned, each as
    ``{start, stop, length, mean_sw_dn_ds, min_sw_dn_ds}``.
    """
    entries = sorted(
        (e for e in _positions(landscape) if isinstance(e.get("protein_pos"), int)),
        key=lambda e: int(e["protein_pos"]),
    )
    runs: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def _flush() -> None:
        if len(current) >= min_run:
            scores = [float(e["sw_dn_ds"]) for e in current]
            runs.append(
                {
                    "start": int(current[0]["protein_pos"]),
                    "stop": int(current[-1]["protein_pos"]),
                    "length": len(current),
                    "mean_sw_dn_ds": sum(scores) / len(scores),
                    "min_sw_dn_ds": min(scores),
                }
            )

    prev_pos: int | None = None
    for entry in entries:
        score = entry.get("sw_dn_ds")
        pos = int(entry["protein_pos"])
        contiguous = prev_pos is None or pos == prev_pos + 1
        intolerant = isinstance(score, (int, float)) and float(score) < threshold
        if intolerant and (contiguous or not current):
            current.append(entry)
        elif intolerant:
            _flush()
            current = [entry]
        else:
            _flush()
            current = []
        prev_pos = pos
    _flush()

    runs.sort(key=lambda r: float(r["mean_sw_dn_ds"]))
    return runs[:top_n]


def _as_int(value: object) -> int:
    """Coerce a possibly-``None`` count to ``int`` (``None`` -> ``0``)."""
    return int(value) if isinstance(value, (int, float)) else 0
