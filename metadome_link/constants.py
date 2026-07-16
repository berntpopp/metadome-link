"""Domain constants for metadome-link: schema/data versions, citation, caveats, limits.

MetaDome data is GRCh37/hg19, frozen at gnomAD r2.0.2 and ClinVar 2018-06-03
(Gencode v19, Pfam 30.0). ``METADOME_DATA_VERSION`` pins the upstream release;
the on-disk result cache and ``capabilities_version`` derive from it. Bump it
manually if MetaDome ships a new release.
"""

from __future__ import annotations

import re

#: Bumped whenever the on-disk SQLite result-cache schema changes.
SCHEMA_VERSION = "1"

#: Pinned MetaDome upstream data release. Cache keys + capabilities_version derive
#: from this; bump manually if MetaDome updates.
METADOME_DATA_VERSION = "gencode19-gnomad2.0.2-clinvar20180603-pfam30-app1.0.1"

#: Structured component versions of the pinned MetaDome release. Surfaced in
#: ``_meta.data_versions`` on EVERY response (the hg19/data-currency caveat surface).
DATA_VERSIONS: dict[str, str] = {
    "assembly": "GRCh37",
    "gencode": "v19",
    "gnomad": "r2.0.2",
    "clinvar": "2018-06-03",
    "pfam": "30.0",
    "metadome_app": "1.0.1",
}

#: Canonical citation pasted verbatim into capability/_meta/record payloads.
RECOMMENDED_CITATION = (
    "MetaDome: Pathogenicity analysis of genetic variants through aggregation of "
    "homologous human protein domains. Wiel L, Baakman C, Gilissen D, Veltman JA, "
    "Vriend G, Gilissen C. Human Mutation. 2019;40(8):1030-1038. "
    "doi:10.1002/humu.23798"
)

#: License attribution for the MetaDome software/data.
METADOME_LICENSE = "MIT (https://github.com/laurensvdwiel/metadome)"

#: Research-use disclaimer surfaced in instructions + capabilities + resources.
RESEARCH_USE_NOTICE = (
    "Research use only; not for clinical decision support, diagnosis, treatment, "
    "or patient management."
)

#: Prominent data-currency caveat (the hg19 / historical-counts warning).
DATA_CURRENCY_CAVEAT = (
    "MetaDome data are GRCh37/hg19 with gnomAD r2.0.2 and ClinVar 2018-06-03; "
    "per-residue ClinVar annotations are historical and MetaDome does not provide true "
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

#: Ensembl transcript id with a version suffix, e.g. ``ENST00000269305.4``.
ENST_RE = re.compile(r"^ENST\d{11}\.\d+$")
