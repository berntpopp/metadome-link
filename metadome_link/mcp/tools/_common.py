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

from pydantic import BeforeValidator, Field, StrictFloat, StrictInt, WithJsonSchema

from metadome_link.constants import (
    MAX_PAGE_LIMIT,
    MAX_PROTEIN_POSITION,
)

#: Output-verbosity selector shared by every data tool (default ``compact``).
ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(description="Output verbosity; default compact, minimal = essentials only."),
]

#: A versioned Ensembl transcript id (the ``.N`` version suffix is required).
TranscriptIdArg = Annotated[
    str,
    Field(
        description="Versioned Ensembl transcript id (with .N suffix), from resolve_transcript.",
        examples=["ENST00000269305.9"],
    ),
]

#: A free-text gene symbol OR a versioned ENST id, for resolve_transcript.
GeneOrIdArg = Annotated[
    str,
    Field(
        description="HGNC gene symbol (e.g. TP53) or versioned ENST id.",
        examples=["TP53"],
    ),
]

#: A single 1-based protein residue position.
PositionArg = Annotated[
    StrictInt,
    Field(
        ge=1,
        le=MAX_PROTEIN_POSITION,
        description="1-based protein residue position.",
        examples=[175],
    ),
]

#: Optional 1-based protein coordinate, used for inclusive range bounds.
OptionalPositionArg = Annotated[
    StrictInt | None,
    Field(
        ge=1,
        le=MAX_PROTEIN_POSITION,
        description="1-based protein residue position; range bounds are inclusive.",
    ),
    WithJsonSchema(
        {
            "type": ["integer", "null"],
            "minimum": 1,
            "maximum": MAX_PROTEIN_POSITION,
            "description": "1-based protein residue position; range bounds are inclusive.",
        }
    ),
]


def _require_finite_real(value: object) -> object:
    """Reject coercive, boolean, and non-finite analysis threshold values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold must be a finite real number")
    try:
        finite = math.isfinite(value)
    except OverflowError, TypeError, ValueError:
        finite = False
    if not finite:
        raise ValueError("threshold must be a finite real number")
    return value


def _threshold_schema(schema: dict[str, object]) -> None:
    """Keep the public JSON Schema on standard draft-2020-12 keywords."""
    schema.pop("gt", None)
    schema.pop("le", None)
    schema["exclusiveMinimum"] = 0.0
    schema["maximum"] = 2.0


# StrictFloat accepts JSON integers as real numbers but rejects strings/bools;
# the before-validator adds the finite-value requirement.
ThresholdArg = Annotated[
    StrictFloat,
    BeforeValidator(_require_finite_real),
    Field(
        gt=0.0,
        le=2.0,
        json_schema_extra=_threshold_schema,
        description="sw_dn_ds cutoff in (0, 2]; residues below it count as intolerant.",
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
        description="1-based protein residue positions to compare.",
        examples=[[35, 175]],
    ),
]

#: Page size for paginated list results.
LimitArg = Annotated[
    StrictInt,
    Field(
        ge=1,
        le=MAX_PAGE_LIMIT,
        description="Rows per page.",
    ),
]

#: Zero-based row offset into a paginated list result.
OffsetArg = Annotated[
    StrictInt,
    Field(ge=0, description="Rows to skip; pass the previous pagination.next_offset."),
]

#: Variant-source selector for explicitly-scoped residue and homolog evidence.
SourceArg = Annotated[
    Literal["both", "gnomad", "clinvar"],
    Field(description="Variant evidence to include: gnomad, clinvar or both."),
]
