"""Domain constants for metadome-link: schema/data versions, citation, caveats, limits."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

#: Bumped whenever the on-disk SQLite result-cache schema changes.
SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class DataProfile:
    """Immutable provenance identity for one live MetaDome build namespace."""

    genome_build: str
    data_version: str
    data_versions: Mapping[str, str]
    data_currency_caveat: str


_PROFILE_37_VERSIONS = MappingProxyType(
    {
        "assembly": "GRCh37.p13",
        "gencode": "v19",
        "uniprot": "2025_01",
        "gnomad": "r2.0.2",
        "clinvar": "2025-10-06",
        "pfam": "37.4",
        "metadome_app": "2.0",
        "data_doi": "10.5281/zenodo.19376150",
    }
)
_PROFILE_38_VERSIONS = MappingProxyType(
    {
        "assembly": "GRCh38.p14",
        "gencode": "v45",
        "uniprot": "2025_01",
        "gnomad": "v4.1",
        "clinvar": "2025-10-06",
        "pfam": "37.4",
        "metadome_app": "2.0",
        "data_doi": "10.5281/zenodo.19376150",
    }
)

DATA_PROFILES: Mapping[str, DataProfile] = MappingProxyType(
    {
        "GRCh37.p13": DataProfile(
            genome_build="GRCh37.p13",
            data_version="metadome2.0-grch37.p13-gencode19-uniprot2025_01-pfam37.4-gnomad2.0.2-clinvar2025-10-06",
            data_versions=_PROFILE_37_VERSIONS,
            data_currency_caveat=(
                "MetaDome 2.0 data use GRCh37.p13/hg19, GENCODE v19, UniProt 2025_01, "
                "Pfam 37.4, gnomAD r2.0.2, and ClinVar 2025-10-06; MetaDome does not "
                "provide true per-residue gnomAD counts."
            ),
        ),
        "GRCh38.p14": DataProfile(
            genome_build="GRCh38.p14",
            data_version="metadome2.0-grch38.p14-gencode45-uniprot2025_01-pfam37.4-gnomad4.1-clinvar2025-10-06",
            data_versions=_PROFILE_38_VERSIONS,
            data_currency_caveat=(
                "MetaDome 2.0 data use GRCh38.p14, GENCODE v45, UniProt 2025_01, "
                "Pfam 37.4, gnomAD v4.1, and ClinVar 2025-10-06; MetaDome does not "
                "provide true per-residue gnomAD counts."
            ),
        ),
    }
)

SUPPORTED_GENOME_BUILDS = tuple(DATA_PROFILES)


def data_profile(genome_build: str) -> DataProfile:
    """Return the exact profile for a supported API namespace."""
    try:
        return DATA_PROFILES[genome_build]
    except KeyError:
        raise ValueError(
            f"Unsupported MetaDome genome build; choose one of {SUPPORTED_GENOME_BUILDS}."
        ) from None


DEFAULT_DATA_PROFILE = DATA_PROFILES["GRCh38.p14"]

# Backwards-compatible default aliases. Runtime consumers must use ``data_profile``.
METADOME_DATA_VERSION = DEFAULT_DATA_PROFILE.data_version
DATA_VERSIONS: dict[str, str] = dict(DEFAULT_DATA_PROFILE.data_versions)

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
DATA_CURRENCY_CAVEAT = DEFAULT_DATA_PROFILE.data_currency_caveat + (
    " Its Pfam meta-domain aggregates can include other genes; use live gnomAD/ClinVar "
    "for current evidence."
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
