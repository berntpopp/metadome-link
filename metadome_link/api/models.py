"""Thin typed shapes for MetaDome API payloads.

The :class:`~metadome_link.api.client.MetaDomeClient` returns **plain dicts** so
that the service layer can shape them freely. These ``TypedDict`` definitions
document the normalized shapes and give downstream code optional structural
typing; nothing at runtime is coerced into these classes.

Normalization applied by the client (see ``client.py``):

- ``get_transcripts`` splits the upstream ``refseq_nm_numbers`` comma-string into
  a ``refseq_ids`` list and exposes MetaDome v2's MANE transcript annotation.
- ``get_result`` / ``get_metadomain_annotation`` coerce every ``clinvar_ID`` to a
  ``str`` (upstream returns a string in ``/result/`` but a float in
  ``/get_metadomain_annotation/``).
"""

from __future__ import annotations

import math
from typing import Any, TypedDict

from metadome_link.exceptions import UpstreamSchemaError
from metadome_link.identifiers import is_transcript_id


class TranscriptSummary(TypedDict):
    """One normalized transcript entry from ``GET /get_transcripts/<gene>``."""

    gencode_id: str
    aa_length: int
    has_protein_data: bool
    mane_transcript_type: str
    refseq_ids: list[str]


class Domain(TypedDict, total=False):
    """A Pfam domain entry from the ``domains`` list of a landscape result."""

    ID: str
    Name: str
    start: int
    stop: int
    metadomain: bool
    meta_domain_alignment_depth: int


class LandscapePosition(TypedDict, total=False):
    """One residue entry from ``positional_annotation`` of a landscape result.

    ``domains`` maps a Pfam id to either ``None`` (in-domain, no meta-domain
    context) or a meta-domain entry object. ``ClinVar`` is present only when at
    least one ClinVar variant maps to the residue; each entry's ``clinvar_ID``
    has been coerced to ``str``.
    """

    protein_pos: int
    chr: str
    chr_positions: str
    cdna_pos: str
    strand: str
    ref_aa: str
    ref_aa_triplet: str
    ref_codon: str
    sw_dn_ds: float | None
    sw_coverage: float
    sw_size: int
    domains: dict[str, object]
    ClinVar: list[dict[str, object]]


_TRANSCRIPT_FIELDS = (
    "gencode_id",
    "aa_length",
    "has_protein_data",
    "mane_transcript_type",
    "refseq_nm_numbers",
)
_POSITION_FIELDS: dict[str, tuple[type[object], ...]] = {
    "cdna_pos": (str,),
    "chr": (str,),
    "chr_positions": (str,),
    "domains": (dict,),
    "protein_pos": (int,),
    "ref_aa": (str,),
    "ref_aa_triplet": (str,),
    "ref_codon": (str,),
    "strand": (str,),
    "sw_coverage": (int, float),
    "sw_dn_ds": (int, float, type(None)),
    "sw_size": (int,),
}
_DOMAIN_FIELDS: dict[str, tuple[type[object], ...]] = {
    "normal_variant_count": (int, float),
    "normal_missense_variant_count": (int, float),
    "pathogenic_variant_count": (int, float),
    "pathogenic_missense_variant_count": (int, float),
}
_VARIANT_FIELDS: dict[str, tuple[type[object], ...]] = {
    "alt": (str,),
    "alt_aa": (str,),
    "alt_aa_triplet": (str,),
    "alt_codon": (str,),
    "pos": (int,),
    "ref": (str,),
    "type": (str,),
}
_METADOMAIN_VARIANT_FIELDS: dict[str, tuple[type[object], ...]] = {
    **_VARIANT_FIELDS,
    "cdna_pos": (str,),
    "chr": (str,),
    "chr_positions": (str,),
    "gene_name": (str,),
    "protein_pos": (int,),
    "ref_aa": (str,),
    "ref_aa_triplet": (str,),
    "ref_codon": (str,),
    "strand": (str,),
}
_CLINVAR_FIELDS = {
    **_VARIANT_FIELDS,
    "clinvar_ID": (str, int, float),
}
_NORMAL_VARIANT_FIELDS = {"allele_count", "allele_number"}
_PATHOGENIC_VARIANT_FIELDS = {"clinvar_ID"}


def _schema_error(path: str) -> UpstreamSchemaError:
    """Build the non-retryable typed error shared by upstream validators."""
    return UpstreamSchemaError(
        "MetaDome upstream returned an invalid response schema.",
        field=path,
    )


def _is_finite_number(value: object) -> bool:
    """Accept JSON numbers only when they are finite and not booleans."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_valid_clinvar_id(value: object) -> bool:
    """Accept the numeric forms emitted by the two upstream v2 endpoints."""
    if isinstance(value, str):
        return (
            bool(value)
            and all("0" <= character <= "9" for character in value)
            and bool(value.lstrip("0"))
        )
    return _is_integer_at_least(value, 1)


def _is_finite_integer(value: object) -> bool:
    """Accept an integer or integer-valued finite float, excluding booleans."""
    return _is_finite_number(value) and (
        isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    )


def _is_nonnegative_integer_number(value: object) -> bool:
    """Validate count values represented as JSON integers or integral floats."""
    return _is_integer_at_least(value, 0)


def _is_integer_at_least(value: object, minimum: int) -> bool:
    """Check an integral finite numeric value against an inclusive lower bound."""
    return _is_finite_integer(value) and isinstance(value, (int, float)) and value >= minimum


def _validate_variant_records(
    raw: object,
    path: str,
    *,
    pathogenic: bool,
) -> list[dict[str, Any]]:
    """Validate one endpoint-6 variant list without coercing upstream values."""
    if not isinstance(raw, list):
        raise _schema_error(path)
    required = set(_METADOMAIN_VARIANT_FIELDS)
    required.update(_PATHOGENIC_VARIANT_FIELDS if pathogenic else _NORMAL_VARIANT_FIELDS)
    validated: list[dict[str, Any]] = []
    for index, variant in enumerate(raw):
        item_path = f"{path}[{index}]"
        if not isinstance(variant, dict) or any(field not in variant for field in required):
            raise _schema_error(item_path)
        if set(variant) != required:
            raise _schema_error(item_path)
        for field, types in _METADOMAIN_VARIANT_FIELDS.items():
            value = variant[field]
            if not isinstance(value, types) or (
                field in {"pos", "protein_pos"} and isinstance(value, bool)
            ):
                raise _schema_error(f"{item_path}.{field}")
        if not isinstance(variant["pos"], int) or variant["pos"] < 1:
            raise _schema_error(f"{item_path}.pos")
        if not isinstance(variant["protein_pos"], int) or variant["protein_pos"] < 1:
            raise _schema_error(f"{item_path}.protein_pos")
        if pathogenic:
            clinvar_id = variant["clinvar_ID"]
            if not _is_integer_at_least(clinvar_id, 1):
                raise _schema_error(f"{item_path}.clinvar_ID")
        else:
            for field in _NORMAL_VARIANT_FIELDS:
                if not _is_nonnegative_integer_number(variant[field]):
                    raise _schema_error(f"{item_path}.{field}")
        validated.append(variant)
    return validated


def _validate_position_domains(raw: object, path: str) -> None:
    """Validate Pfam memberships nested inside a positional result row."""
    if not isinstance(raw, dict):
        raise _schema_error(path)
    for pfam_id, mapping in raw.items():
        domain_path = f"{path}.{pfam_id}"
        if not isinstance(pfam_id, str) or not pfam_id:
            raise _schema_error(path)
        if mapping is None:
            continue
        if not isinstance(mapping, dict):
            raise _schema_error(domain_path)
        if any(field not in mapping for field in _DOMAIN_FIELDS) or "consensus_pos" not in mapping:
            raise _schema_error(domain_path)
        if set(mapping) != {*_DOMAIN_FIELDS, "consensus_pos"}:
            raise _schema_error(domain_path)
        consensus = mapping["consensus_pos"]
        if (
            not isinstance(consensus, list)
            or not consensus
            or any(
                not isinstance(pos, int) or isinstance(pos, bool) or pos < 1 for pos in consensus
            )
        ):
            raise _schema_error(f"{domain_path}.consensus_pos")
        for field in _DOMAIN_FIELDS:
            value = mapping[field]
            if not _is_finite_number(value) or (isinstance(value, (int, float)) and value < 0):
                raise _schema_error(f"{domain_path}.{field}")


def validate_metadomain_blocks(raw: object) -> dict[str, dict[str, Any]]:
    """Validate endpoint-6 Pfam blocks and both nested variant collections."""
    if not isinstance(raw, dict):
        raise _schema_error("metadomain_annotation")
    validated: dict[str, dict[str, Any]] = {}
    for pfam_id, block in raw.items():
        path = str(pfam_id)
        if not isinstance(pfam_id, str) or not pfam_id or not isinstance(block, dict):
            raise _schema_error(path)
        required = {"alignment_depth", "normal_variants", "pathogenic_variants"}
        if any(field not in block for field in required):
            raise _schema_error(path)
        depth = block["alignment_depth"]
        if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
            raise _schema_error(f"{path}.alignment_depth")
        _validate_variant_records(
            block["normal_variants"], f"{path}.normal_variants", pathogenic=False
        )
        _validate_variant_records(
            block["pathogenic_variants"], f"{path}.pathogenic_variants", pathogenic=True
        )
        validated[pfam_id] = block
    return validated


def validate_transcript_entries(raw: object) -> list[dict[str, Any]]:
    """Validate the v2 transcript list before normalizing its values."""
    if not isinstance(raw, list):
        raise _schema_error("transcript_ids")
    validated: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        path = f"transcript_ids[{index}]"
        if not isinstance(entry, dict):
            raise _schema_error(path)
        for field in _TRANSCRIPT_FIELDS:
            if field not in entry:
                raise _schema_error(f"{path}.{field}")
        gencode_id = entry["gencode_id"]
        if not isinstance(gencode_id, str) or not is_transcript_id(gencode_id):
            raise _schema_error(f"{path}.gencode_id")
        aa_length = entry["aa_length"]
        if not isinstance(aa_length, int) or isinstance(aa_length, bool) or aa_length < 0:
            raise _schema_error(f"{path}.aa_length")
        if not isinstance(entry["has_protein_data"], bool):
            raise _schema_error(f"{path}.has_protein_data")
        if not isinstance(entry["mane_transcript_type"], str):
            raise _schema_error(f"{path}.mane_transcript_type")
        if not isinstance(entry["refseq_nm_numbers"], str):
            raise _schema_error(f"{path}.refseq_nm_numbers")
        validated.append(entry)
    return validated


def validate_positional_annotations(raw: object) -> list[dict[str, Any]]:
    """Validate every result row and its optional nested ClinVar records."""
    if not isinstance(raw, list):
        raise _schema_error("positional_annotation")
    validated: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        path = f"positional_annotation[{index}]"
        if not isinstance(entry, dict):
            raise _schema_error(path)
        for field, types in _POSITION_FIELDS.items():
            if field not in entry:
                raise _schema_error(f"{path}.{field}")
            value = entry[field]
            if isinstance(value, bool) or not isinstance(value, types):
                raise _schema_error(f"{path}.{field}")
            if (
                field in {"sw_coverage", "sw_dn_ds"}
                and value is not None
                and (
                    not _is_finite_number(value) or (isinstance(value, (int, float)) and value < 0)
                )
            ):
                raise _schema_error(f"{path}.{field}")
            if field in {"protein_pos", "sw_size"} and isinstance(value, int) and value < 1:
                raise _schema_error(f"{path}.{field}")
            if field == "sw_coverage" and isinstance(value, (int, float)) and value > 1:
                raise _schema_error(f"{path}.{field}")
        _validate_position_domains(entry["domains"], f"{path}.domains")
        variants = entry.get("ClinVar")
        if variants is not None:
            if not isinstance(variants, list):
                raise _schema_error(f"{path}.ClinVar")
            for variant_index, variant in enumerate(variants):
                variant_path = f"{path}.ClinVar[{variant_index}]"
                if not isinstance(variant, dict):
                    raise _schema_error(variant_path)
                if set(variant) != set(_CLINVAR_FIELDS):
                    raise _schema_error(variant_path)
                for field, types in _CLINVAR_FIELDS.items():
                    if field not in variant or not isinstance(variant[field], types):
                        raise _schema_error(f"{variant_path}.{field}")
                clinvar_id = variant["clinvar_ID"]
                if not _is_valid_clinvar_id(clinvar_id):
                    raise _schema_error(f"{variant_path}.clinvar_ID")
                if isinstance(variant["pos"], bool):
                    raise _schema_error(f"{variant_path}.pos")
                if not isinstance(variant["pos"], int) or variant["pos"] < 1:
                    raise _schema_error(f"{variant_path}.pos")
        validated.append(entry)
    return validated
