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
from metadome_link.mcp._sanitize import sanitize_message


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
_DOMAIN_OPTIONAL_FIELDS: dict[str, tuple[type[object], ...]] = {
    "pathogenic_variant_count_per_clinsig": (dict,),
    "pathogenic_missense_variant_count_per_clinsig": (dict,),
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
_METADOMAIN_OPTIONAL_FIELDS: dict[str, tuple[type[object], ...]] = {
    "exon_numbers": (str,),
    "clinvar_clinsig": (str,),
}
_CLINVAR_FIELDS = {
    **_VARIANT_FIELDS,
    "clinvar_ID": (str, int, float),
}
_CLINVAR_OPTIONAL_FIELDS = {"clinvar_clinsig": (str,)}
_POSITION_OPTIONAL_FIELDS = {"exon_numbers": (str,), "ClinVar": (list,)}
_RESULT_FIELDS = {
    "transcript_id": (str,),
    "gene_name": (str,),
    "protein_ac": (str,),
    "refseq_ids": (str, list),
    "domains": (list,),
    "positional_annotation": (list,),
}
_NORMAL_VARIANT_FIELDS = {"allele_count", "allele_number"}
_PATHOGENIC_VARIANT_FIELDS = {"clinvar_ID"}
_VARIANT_TYPES = frozenset({"missense", "synonymous", "nonsense"})
_STRANDS = frozenset({"+", "-"})
# Safety bounds for finite integer fields documented by the v2 contract. These
# exceed every live value while preventing unbounded Python integers from
# reaching shaping, JSON encoding, or downstream arithmetic.
MAX_ALIGNMENT_DEPTH = 100_000
MAX_GENOMIC_POSITION = 1_000_000_000
_REQUIRED_RESULT_FIELDS = frozenset(_RESULT_FIELDS)


def _schema_error(path: str) -> UpstreamSchemaError:
    """Build the non-retryable typed error shared by upstream validators."""
    return UpstreamSchemaError(
        "MetaDome upstream returned an invalid response schema.",
        field=sanitize_message(path),
    )


def _is_finite_number(value: object) -> bool:
    """Accept JSON numbers only when they are finite and not booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


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


def _is_integer_at_least(value: object, minimum: int, maximum: int | None = None) -> bool:
    """Check an integral finite numeric value against an inclusive lower bound."""
    return (
        _is_finite_integer(value)
        and isinstance(value, (int, float))
        and value >= minimum
        and (maximum is None or value <= maximum)
    )


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
        optional = {"exon_numbers"}
        if pathogenic:
            optional.add("clinvar_clinsig")
        if set(variant) - required - optional:
            raise _schema_error(item_path)
        for field, types in _METADOMAIN_VARIANT_FIELDS.items():
            value = variant[field]
            if not isinstance(value, types) or (
                field in {"pos", "protein_pos"} and isinstance(value, bool)
            ):
                raise _schema_error(f"{item_path}.{field}")
        if variant["type"] not in _VARIANT_TYPES:
            raise _schema_error(f"{item_path}.type")
        if variant["strand"] not in _STRANDS:
            raise _schema_error(f"{item_path}.strand")
        for field in optional:
            if field in variant and not isinstance(
                variant[field], _METADOMAIN_OPTIONAL_FIELDS[field]
            ):
                raise _schema_error(f"{item_path}.{field}")
        if not _is_integer_at_least(variant["pos"], 1, MAX_GENOMIC_POSITION):
            raise _schema_error(f"{item_path}.pos")
        if not _is_integer_at_least(variant["protein_pos"], 1):
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
        required = {*_DOMAIN_FIELDS, "consensus_pos"}
        allowed = required | set(_DOMAIN_OPTIONAL_FIELDS)
        if any(field not in mapping for field in required):
            raise _schema_error(domain_path)
        if set(mapping) - allowed:
            raise _schema_error(domain_path)
        consensus = mapping["consensus_pos"]
        if (
            not isinstance(consensus, list)
            or not consensus
            or any(not _is_integer_at_least(pos, 1) for pos in consensus)
        ):
            raise _schema_error(f"{domain_path}.consensus_pos")
        for field in _DOMAIN_FIELDS:
            value = mapping[field]
            if not _is_nonnegative_integer_number(value):
                raise _schema_error(f"{domain_path}.{field}")
        for field in _DOMAIN_OPTIONAL_FIELDS:
            if field not in mapping:
                continue
            value = mapping[field]
            if not isinstance(value, dict):
                raise _schema_error(f"{domain_path}.{field}")
            for significance, count in value.items():
                if not isinstance(significance, str) or not significance:
                    raise _schema_error(f"{domain_path}.{field}")
                if not _is_nonnegative_integer_number(count):
                    raise _schema_error(f"{domain_path}.{field}.{significance}")


def _validate_result_domains(raw: object, path: str) -> list[dict[str, Any]]:
    """Validate the top-level Pfam domain list from a result document."""
    if not isinstance(raw, list):
        raise _schema_error(path)
    fields = {
        "ID": (str,),
        "Name": (str,),
        "meta_domain_alignment_depth": (int,),
        "metadomain": (bool,),
        "start": (int,),
        "stop": (int,),
    }
    validated: list[dict[str, Any]] = []
    for index, domain in enumerate(raw):
        domain_path = f"{path}[{index}]"
        if not isinstance(domain, dict) or set(domain) != set(fields):
            raise _schema_error(domain_path)
        for field, types in fields.items():
            value = domain[field]
            if not isinstance(value, types) or (field != "metadomain" and isinstance(value, bool)):
                raise _schema_error(f"{domain_path}.{field}")
        if not _is_integer_at_least(domain["meta_domain_alignment_depth"], 0, MAX_ALIGNMENT_DEPTH):
            raise _schema_error(f"{domain_path}.meta_domain_alignment_depth")
        if not _is_integer_at_least(domain["start"], 1) or not _is_integer_at_least(
            domain["stop"], 1
        ):
            raise _schema_error(f"{domain_path}.start")
        if domain["stop"] < domain["start"]:
            raise _schema_error(f"{domain_path}.stop")
        validated.append(domain)
    return validated


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
        if set(block) != required:
            raise _schema_error(path)
        depth = block["alignment_depth"]
        if not _is_integer_at_least(depth, 0, MAX_ALIGNMENT_DEPTH):
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
        if not _is_integer_at_least(aa_length, 0):
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
        allowed = set(_POSITION_FIELDS) | set(_POSITION_OPTIONAL_FIELDS)
        if set(entry) - allowed:
            unknown = next(iter(set(entry) - allowed))
            raise _schema_error(f"{path}.{unknown}")
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
            if field in {"protein_pos", "sw_size"} and not _is_integer_at_least(value, 1):
                raise _schema_error(f"{path}.{field}")
            if field == "sw_coverage" and isinstance(value, (int, float)) and value > 1:
                raise _schema_error(f"{path}.{field}")
            if field == "strand" and value not in _STRANDS:
                raise _schema_error(f"{path}.{field}")
        if "exon_numbers" in entry and not isinstance(entry["exon_numbers"], str):
            raise _schema_error(f"{path}.exon_numbers")
        _validate_position_domains(entry["domains"], f"{path}.domains")
        variants = entry.get("ClinVar")
        if variants is not None:
            if not isinstance(variants, list):
                raise _schema_error(f"{path}.ClinVar")
            for variant_index, variant in enumerate(variants):
                variant_path = f"{path}.ClinVar[{variant_index}]"
                if not isinstance(variant, dict):
                    raise _schema_error(variant_path)
                if set(variant) - set(_CLINVAR_FIELDS) - set(_CLINVAR_OPTIONAL_FIELDS):
                    raise _schema_error(variant_path)
                for field, types in _CLINVAR_FIELDS.items():
                    if field not in variant or not isinstance(variant[field], types):
                        raise _schema_error(f"{variant_path}.{field}")
                for field, types in _CLINVAR_OPTIONAL_FIELDS.items():
                    if field in variant and not isinstance(variant[field], types):
                        raise _schema_error(f"{variant_path}.{field}")
                if variant["type"] not in _VARIANT_TYPES:
                    raise _schema_error(f"{variant_path}.type")
                clinvar_id = variant["clinvar_ID"]
                if not _is_valid_clinvar_id(clinvar_id):
                    raise _schema_error(f"{variant_path}.clinvar_ID")
                if isinstance(variant["pos"], bool):
                    raise _schema_error(f"{variant_path}.pos")
                if not _is_integer_at_least(variant["pos"], 1, MAX_GENOMIC_POSITION):
                    raise _schema_error(f"{variant_path}.pos")
        validated.append(entry)
    return validated


def validate_result_document(raw: object) -> dict[str, Any]:
    """Validate live result top-level shapes and nested positional records."""
    if not isinstance(raw, dict):
        raise _schema_error("result")
    allowed = set(_RESULT_FIELDS)
    if set(raw) - allowed:
        unknown = next(iter(set(raw) - allowed))
        raise _schema_error(unknown)
    positions = validate_positional_annotations(raw.get("positional_annotation"))
    missing = _REQUIRED_RESULT_FIELDS - set(raw)
    if missing:
        raise _schema_error(next(field for field in _RESULT_FIELDS if field in missing))
    for field, types in _RESULT_FIELDS.items():
        if field not in raw:
            continue
        value = raw[field]
        if not isinstance(value, types):
            raise _schema_error(field)
    if "domains" in raw:
        _validate_result_domains(raw["domains"], "domains")
    refseq = raw.get("refseq_ids")
    if isinstance(refseq, list) and any(not isinstance(item, str) for item in refseq):
        raise _schema_error("refseq_ids")
    result = dict(raw)
    result["positional_annotation"] = positions
    return result


def validate_cached_landscape(
    raw: object | None, expected_transcript_id: str
) -> dict[str, Any] | None:
    """Apply the complete result contract to a cache value before serving it."""
    if raw is None:
        return None
    result = validate_result_document(raw)
    if result["transcript_id"] != expected_transcript_id:
        raise _schema_error("transcript_id")
    return result
