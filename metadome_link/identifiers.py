"""Identifier normalisation and validation for metadome-link.

MetaDome keys everything on a versioned Ensembl transcript id
(``ENST00000269305.9`` — the ``.N`` version is **required**; ``submit_visualization``
rejects an unversioned id). Gene symbols are normalised to upper-case for the
case-insensitive ``/get_transcripts/<gene>`` endpoint.
"""

from __future__ import annotations

import re

from metadome_link.constants import ENST_RE
from metadome_link.exceptions import InvalidInputError, UpstreamSchemaError

#: Recovery hint reused by ``validate_transcript_id`` and surfaced on the envelope.
_TRANSCRIPT_HINT = "Ensembl transcript id with version, e.g. ENST00000269305.9"


def normalize_gene_symbol(s: str) -> str:
    """Normalise a gene symbol: strip surrounding whitespace and upper-case it."""
    return s.strip().upper()


# Gene id namespaces MetaDome is not keyed by (it takes an HGNC symbol), each with the HGNC
# tool and argument that convert it. re.ASCII: matched text is echoed into next_commands.
_FLAGS = re.IGNORECASE | re.ASCII
_FOREIGN_GENE_FORMS = (
    (re.compile(r"ENSG\d{11}(?:\.\d+)?", _FLAGS), "hgnc_resolve_symbol", "query", "{0}"),
    (re.compile(r"HGNC:(\d+)", _FLAGS), "hgnc_resolve_symbol", "query", "HGNC:{1}"),
    (
        re.compile(r"(?:NCBIGene|GeneID|Entrez):(\d+)", _FLAGS),
        "hgnc_resolve_gene_by_xref",
        "value",
        "{1}",
    ),
)


def reject_foreign_gene_id(s: str, *, field: str = "query") -> None:
    """Raise ``InvalidInputError`` for an Ensembl gene, HGNC or NCBI Gene id.

    MetaDome would answer such an id with "no transcripts", which reads as "the gene
    has none" although it was never looked up (Response-Envelope v1 section 2b).
    """
    for pattern, tool, argument, template in _FOREIGN_GENE_FORMS:
        match = pattern.fullmatch(s.strip())
        if match is None:
            continue
        arguments = {argument: template.format(match.group(0), *match.groups())}
        if tool == "hgnc_resolve_gene_by_xref":
            arguments = {"source": "entrez_id", **arguments}
        raise InvalidInputError(
            f"{field} takes an HGNC gene symbol or a versioned ENST id, not an Ensembl gene, "
            "HGNC or NCBI Gene id. MetaDome was not queried.",
            field=field,
            allowed_values=["HGNC gene symbol, e.g. TP53", _TRANSCRIPT_HINT],
            hint="Convert the id to its symbol with the call in _meta.next_commands, then retry.",
            next_commands=[{"tool": tool, "arguments": arguments}],
        )


def require_matching_gene(response: object, requested: str) -> None:
    """Reject a present upstream gene name that is not the requested symbol."""
    if response is not None and (
        not isinstance(response, str)
        or normalize_gene_symbol(response) != normalize_gene_symbol(requested)
    ):
        raise UpstreamSchemaError(
            "MetaDome transcript response has an unexpected gene.", field="gene_name"
        )


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
            f"Invalid transcript_id: expected an {_TRANSCRIPT_HINT}.",
            field="transcript_id",
            hint=_TRANSCRIPT_HINT,
        )
    return candidate


def looks_like_transcript_query(s: str) -> bool:
    """Return True iff the query looks like a transcript id (starts with ``ENST``)."""
    return s.strip().upper().startswith("ENST")
