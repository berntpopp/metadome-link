"""Pure helpers for transcript resolution: sorting, canonical pick, query typing.

A gene symbol maps to many Gencode v19 transcripts. The fleet convention (from
MetaDome's own ``dashboard.js``) is to sort transcripts by ``aa_length``
descending and treat the longest **protein-coding** transcript
(``has_protein_data == True``) as the de-facto canonical choice. Transcripts
without protein data cannot be visualized and are never canonical.

These helpers are deterministic and side-effect free so they can be unit-tested
in isolation and reused by :class:`~metadome_link.services.metadome_service.MetaDomeService`.
"""

from __future__ import annotations

from typing import Any

from metadome_link.identifiers import looks_like_transcript_query


def sort_transcripts(transcripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return *transcripts* sorted by ``aa_length`` descending (stable).

    A missing/``None`` ``aa_length`` sorts last (treated as ``0``).
    """

    def _length(entry: dict[str, Any]) -> int:
        value = entry.get("aa_length")
        return int(value) if isinstance(value, int) else 0

    return sorted(transcripts, key=_length, reverse=True)


def pick_canonical(transcripts: list[dict[str, Any]]) -> str | None:
    """Return the ``gencode_id`` of the canonical transcript, or ``None``.

    The canonical transcript is the **first** ``has_protein_data == True`` entry
    in the supplied (already length-sorted) list — i.e. the longest protein-
    coding transcript. Returns ``None`` when no transcript carries protein data.
    """
    for entry in transcripts:
        if entry.get("has_protein_data"):
            gid = entry.get("gencode_id")
            if isinstance(gid, str):
                return gid
    return None


def detect_query_type(query: str) -> str:
    """Classify a free-text query as ``"id"`` (ENST transcript) or ``"gene"``."""
    return "id" if looks_like_transcript_query(query) else "gene"
