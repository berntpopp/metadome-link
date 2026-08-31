"""Identifier normalisation and validation for metadome-link.

MetaDome keys everything on a versioned Ensembl transcript id
(``ENST00000269305.9`` — the ``.N`` version is **required**; ``submit_visualization``
rejects an unversioned id). Gene symbols are normalised to upper-case for the
case-insensitive ``/get_transcripts/<gene>`` endpoint.
"""

from __future__ import annotations

from metadome_link.constants import ENST_RE
from metadome_link.exceptions import InvalidInputError

#: Recovery hint reused by ``validate_transcript_id`` and surfaced on the envelope.
_TRANSCRIPT_HINT = "Ensembl transcript id with version, e.g. ENST00000269305.9"


def normalize_gene_symbol(s: str) -> str:
    """Normalise a gene symbol: strip surrounding whitespace and upper-case it."""
    return s.strip().upper()


def is_transcript_id(s: str) -> bool:
    """Return True iff ``s`` is a versioned Ensembl transcript id (``ENST...N``)."""
    return bool(ENST_RE.match(s.strip()))


def validate_transcript_id(s: str) -> str:
    """Return the normalised transcript id, or raise ``InvalidInputError``.

    The id must match ``^ENST\\d{11}\\.\\d+$`` (version suffix required), since
    MetaDome rejects unversioned ids on submission.

    Raises:
        InvalidInputError: If ``s`` is not a versioned Ensembl transcript id.
            Carries ``field="transcript_id"`` and a recovery ``hint``.
    """
    candidate = s.strip()
    if not is_transcript_id(candidate):
        raise InvalidInputError(
            f"Invalid transcript id: {s!r}. {_TRANSCRIPT_HINT}",
            field="transcript_id",
            hint=_TRANSCRIPT_HINT,
        )
    return candidate


def looks_like_transcript_query(s: str) -> bool:
    """Return True iff the query looks like a transcript id (starts with ``ENST``)."""
    return s.strip().upper().startswith("ENST")
