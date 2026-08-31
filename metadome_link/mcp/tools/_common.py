"""Shared ``Annotated`` argument types for the MetaDome MCP tools.

These pydantic-annotated aliases keep tool signatures terse and consistent: the
``Field`` descriptions/examples/constraints are the single source of truth for
how each argument is documented and validated across every tool module (Tasks
9-13 import from here). Keeping them centralised also means the arg-validation
middleware and the discovery surface describe identical constraints.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StrictFloat, StrictInt

from metadome_link.constants import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PROTEIN_POSITION,
)

#: Output-verbosity selector shared by every data tool (default ``compact``).
ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(description="Verbosity: minimal|compact|standard|full (default compact)."),
]

#: A versioned Ensembl transcript id (the ``.N`` version suffix is required).
TranscriptIdArg = Annotated[
    str,
    Field(
        description="A versioned Ensembl transcript id (the .N version suffix is required), "
        "e.g. ENST00000269305.9. Resolve a gene symbol with resolve_transcript first.",
        examples=["ENST00000269305.9"],
    ),
]

#: A free-text gene symbol OR a versioned ENST id, for resolve_transcript.
GeneOrIdArg = Annotated[
    str,
    Field(
        description="A gene symbol (e.g. TP53) or a versioned Ensembl transcript id "
        "(e.g. ENST00000269305.9). Gene symbols are resolved to candidate transcripts; "
        "a bare ENST id is validated and echoed.",
        examples=["TP53", "ENST00000269305.9"],
    ),
]

#: A single 1-based protein residue position.
PositionArg = Annotated[
    StrictInt,
    Field(
        ge=1,
        le=MAX_PROTEIN_POSITION,
        description=f"1-based protein residue position (1..{MAX_PROTEIN_POSITION}).",
        examples=[273],
    ),
]

#: Optional 1-based protein coordinate, used for inclusive range bounds.
OptionalPositionArg = Annotated[
    StrictInt | None,
    Field(
        ge=1,
        le=MAX_PROTEIN_POSITION,
        description=f"1-based protein residue position (1..{MAX_PROTEIN_POSITION}).",
    ),
]


def _require_finite_real(value: object) -> object:
    """Reject coercive, boolean, and non-finite analysis threshold values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold must be a finite real number")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        finite = False
    if not finite:
        raise ValueError("threshold must be a finite real number")
    return value


# StrictFloat accepts JSON integers as real numbers but rejects strings/bools;
# the before-validator adds the finite-value requirement.
ThresholdArg = Annotated[
    StrictFloat,
    BeforeValidator(_require_finite_real),
    Field(
        gt=0.0,
        le=2.0,
        description=(
            "sw_dn_ds threshold (exclusive upper bound) for intolerant residues "
            "(default 0.5). Lower values identify only the most constrained positions."
        ),
    ),
]

#: A batch of 1-based protein residue positions (e.g. for compare_positions).
PositionsArg = Annotated[
    list[
        Annotated[
            StrictInt,
            Field(ge=1, le=MAX_PROTEIN_POSITION),
        ]
    ],
    Field(
        description="A batch of 1-based protein residue positions to compare side by side.",
        examples=[[175, 248, 273]],
    ),
]

#: Page size for paginated list results.
LimitArg = Annotated[
    StrictInt,
    Field(
        ge=1,
        le=MAX_PAGE_LIMIT,
        description=f"Maximum rows to return (1..{MAX_PAGE_LIMIT}; default {DEFAULT_PAGE_LIMIT}).",
    ),
]

#: Zero-based row offset into a paginated list result.
OffsetArg = Annotated[
    StrictInt,
    Field(ge=0, description="Zero-based offset into the result list (for paging)."),
]

#: Variant-source selector for explicitly-scoped residue and homolog evidence.
SourceArg = Annotated[
    Literal["both", "gnomad", "clinvar"],
    Field(description="Evidence source to report: both|gnomad|clinvar (default both)."),
]
