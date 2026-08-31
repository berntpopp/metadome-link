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
_CLINVAR_FIELDS: dict[str, tuple[type[object], ...]] = {
    "alt": (str,),
    "alt_aa": (str,),
    "alt_aa_triplet": (str,),
    "alt_codon": (str,),
    # /result emits strings; /get_metadomain_annotation emits integral floats.
    "clinvar_ID": (str, int, float),
    "pos": (int,),
    "ref": (str,),
    "type": (str,),
}


def _schema_error(path: str) -> UpstreamSchemaError:
    """Build the non-retryable typed error shared by upstream validators."""
    return UpstreamSchemaError(
        "MetaDome upstream returned an invalid response schema.",
        field=path,
    )


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
        variants = entry.get("ClinVar")
        if variants is not None:
            if not isinstance(variants, list):
                raise _schema_error(f"{path}.ClinVar")
            for variant_index, variant in enumerate(variants):
                variant_path = f"{path}.ClinVar[{variant_index}]"
                if not isinstance(variant, dict):
                    raise _schema_error(variant_path)
                for field, types in _CLINVAR_FIELDS.items():
                    if field not in variant or not isinstance(variant[field], types):
                        raise _schema_error(f"{variant_path}.{field}")
                if isinstance(variant["clinvar_ID"], bool) or (
                    isinstance(variant["clinvar_ID"], float)
                    and not variant["clinvar_ID"].is_integer()
                ):
                    raise _schema_error(f"{variant_path}.clinvar_ID")
                if isinstance(variant["pos"], bool):
                    raise _schema_error(f"{variant_path}.pos")
        validated.append(entry)
    return validated
