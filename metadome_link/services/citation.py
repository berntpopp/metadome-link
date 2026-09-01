"""Citation helpers for MetaDome payloads.

``recommended_citation`` returns the verbatim Wiel et al. 2019 citation string.
Transcript identity is carried by the surrounding structured response fields,
never appended to the bibliographic record.

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
    """Return the canonical verbatim MetaDome citation.

    Parameters
    ----------
    transcript_id:
        Accepted for API compatibility; identity remains a separate field.
    gene_name:
        Reserved for future use (e.g. gene-level citation variants).  Currently
        has no effect on the returned string; included so callers can pass it
        for forward compatibility.

    Returns
    -------
    str
        The verbatim Wiel 2019 citation.
    """
    del transcript_id, gene_name
    return RECOMMENDED_CITATION


def citation_template() -> str:
    """Return the bare citation template string.

    This is identical to ``RECOMMENDED_CITATION`` from the constants module.
    Exposed here so service-layer code imports citations from a single place
    (``metadome_link.services.citation``) rather than reaching into constants
    directly.
    """
    return RECOMMENDED_CITATION
