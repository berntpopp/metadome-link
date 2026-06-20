"""Thin typed shapes for MetaDome API payloads.

The :class:`~metadome_link.api.client.MetaDomeClient` returns **plain dicts** so
that the service layer can shape them freely. These ``TypedDict`` definitions
document the normalized shapes and give downstream code optional structural
typing; nothing at runtime is coerced into these classes.

Normalization applied by the client (see ``client.py``):

- ``get_transcripts`` splits the upstream ``refseq_nm_numbers`` comma-string into
  a ``refseq_ids`` list and renames the misspelled ``trancript_ids`` key away.
- ``get_result`` / ``get_metadomain_annotation`` coerce every ``clinvar_ID`` to a
  ``str`` (upstream returns a string in ``/result/`` but a float in
  ``/get_metadomain_annotation/``).
"""

from __future__ import annotations

from typing import TypedDict


class TranscriptSummary(TypedDict):
    """One normalized transcript entry from ``GET /get_transcripts/<gene>``."""

    gencode_id: str
    aa_length: int
    has_protein_data: bool
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
