"""Domain constants for metadome-link: schema/data versions, citation, caveats, limits."""

from __future__ import annotations

import re

#: Bumped whenever the on-disk SQLite result-cache schema changes.
SCHEMA_VERSION = "1"

#: Pinned MetaDome upstream data release. Cache keys + capabilities_version derive
#: from this; bump manually if MetaDome updates.
METADOME_DATA_VERSION = (
    "metadome2.0-grch38.p14-gencode45-uniprot2025_01-pfam37.4-gnomad4.1-clinvar2025-10-06"
)

#: Structured component versions of the pinned MetaDome release. Surfaced in
#: ``_meta.data_versions`` on EVERY response (the data-currency caveat surface).
DATA_VERSIONS: dict[str, str] = {
    "assembly": "GRCh38.p14",
    "gencode": "v45",
    "uniprot": "2025_01",
    "gnomad": "v4.1",
    "clinvar": "2025-10-06",
    "pfam": "37.4",
    "metadome_app": "2.0",
    "data_doi": "10.5281/zenodo.19376150",
}

#: Canonical citation pasted verbatim into capability/_meta/record payloads.
RECOMMENDED_CITATION = (
    "MetaDome: Pathogenicity analysis of genetic variants through aggregation of "
    "homologous human protein domains. Wiel L, Baakman C, Gilissen D, Veltman JA, "
    "Vriend G, Gilissen C. Human Mutation. 2019;40(8):1030-1038. "
    "doi:10.1002/humu.23798"
)

#: License attribution for the MetaDome software/data.
METADOME_LICENSE = (
    "MetaDome 2.0 data: CC BY 4.0 (doi:10.5281/zenodo.19376150); "
    "software: MIT (https://github.com/laurensvdwiel/metadome)"
)

#: Research-use disclaimer surfaced in instructions + capabilities + resources.
RESEARCH_USE_NOTICE = (
    "Research use only; not for clinical decision support, diagnosis, treatment, "
    "or patient management."
)

#: Prominent data-currency caveat (the pinned-release / aggregate-counts warning).
DATA_CURRENCY_CAVEAT = (
    "MetaDome 2.0 data use GRCh38.p14, GENCODE v45, UniProt 2025_01, Pfam 37.4, "
    "gnomAD v4.1, and ClinVar 2025-10-06; MetaDome does not provide true "
    "per-residue gnomAD counts. Its Pfam meta-domain aggregates can include other genes; "
    "use live gnomAD/ClinVar for current evidence."
)

#: Provenance carried next to every Pfam meta-domain variant aggregate.  The
#: upstream counts are aligned-homolog aggregates, never evidence at the queried
#: transcript residue.
META_DOMAIN_HOMOLOG_AGGREGATE_PROVENANCE = (
    "Aggregated across aligned Pfam meta-domain homologs and can include other genes; "
    "not residue-level evidence for this transcript."
)

#: MetaDome's landscape payload has no true per-residue gnomAD observations.
RESIDUE_GNOMAD_UNAVAILABLE_REASON = (
    "MetaDome does not provide true residue-level gnomAD counts; do not interpret an "
    "absent meta-domain aggregate as zero population variation."
)

#: Hard cap on positions accepted by a single batch tool call.
MAX_BATCH_POSITIONS = 50

#: Default and maximum page sizes for list-returning tools.
DEFAULT_PAGE_LIMIT = 200
MAX_PAGE_LIMIT = 1000

#: Hard cap on the serialised character length of a successful tool payload's
#: data (the ``_meta`` block is exempt). ~90k chars is a safe margin under the
#: ~25k-token (~100k-char) MCP client response cap, leaving headroom for the
#: ``_meta`` block and JSON-encoding overhead. The envelope runs
#: ``char_budget_guard`` against this so a ``full``-mode tolerance landscape or a
#: deep meta-domain closure cannot overflow the client response budget.
MAX_RESPONSE_CHARS = 90_000

#: Verbosity tiers for ``response_mode`` and the default tier.
RESPONSE_MODES = ["minimal", "compact", "standard", "full"]
DEFAULT_RESPONSE_MODE = "compact"

#: Ensembl transcript id with a version suffix, e.g. ``ENST00000269305.9``.
ENST_RE = re.compile(r"^ENST\d{11}\.\d+$")
