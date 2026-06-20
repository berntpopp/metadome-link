"""Citation helpers for MetaDome payloads.

``recommended_citation`` returns the verbatim Wiel et al. 2019 citation string,
optionally extended with a transcript-specific suffix so downstream tasks can
paste it directly into tool responses without knowing the citation text.

``citation_template`` returns the bare template string used internally for
``recommended_citation`` generation.
"""

from __future__ import annotations

from metadome_link.constants import RECOMMENDED_CITATION


def recommended_citation(
    *,
    transcript_id: str | None = None,
    gene_name: str | None = None,
) -> str:
    """Return the canonical MetaDome citation, optionally suffixed.

    Parameters
    ----------
    transcript_id:
        When supplied, appends `` Transcript {transcript_id}.`` to the base
        citation so callers can reference a specific transcript without
        constructing the citation themselves.
    gene_name:
        Reserved for future use (e.g. gene-level citation variants).  Currently
        has no effect on the returned string; included so callers can pass it
        for forward compatibility.

    Returns
    -------
    str
        The verbatim Wiel 2019 citation, with an optional transcript suffix.
    """
    cit = RECOMMENDED_CITATION
    if transcript_id:
        cit = f"{cit} Transcript {transcript_id}."
    return cit


def citation_template() -> str:
    """Return the bare citation template string.

    This is identical to ``RECOMMENDED_CITATION`` from the constants module.
    Exposed here so service-layer code imports citations from a single place
    (``metadome_link.services.citation``) rather than reaching into constants
    directly.
    """
    return RECOMMENDED_CITATION
