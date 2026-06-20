"""Shared ``Annotated`` argument types for the MetaDome MCP tools.

These pydantic-annotated aliases keep tool signatures terse and consistent: the
``Field`` descriptions/examples/constraints are the single source of truth for
how each argument is documented and validated across every tool module (Tasks
9-13 import from here). Keeping them centralised also means the arg-validation
middleware and the discovery surface describe identical constraints.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from metadome_link.constants import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
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
        "e.g. ENST00000269305.4. Resolve a gene symbol with resolve_transcript first.",
        examples=["ENST00000269305.4"],
    ),
]

#: A free-text gene symbol OR a versioned ENST id, for resolve_transcript.
GeneOrIdArg = Annotated[
    str,
    Field(
        description="A gene symbol (e.g. TP53) or a versioned Ensembl transcript id "
        "(e.g. ENST00000269305.4). Gene symbols are resolved to candidate transcripts; "
        "a bare ENST id is validated and echoed.",
        examples=["TP53", "ENST00000269305.4"],
    ),
]

#: A single 1-based protein residue position.
PositionArg = Annotated[
    int,
    Field(ge=1, description="1-based protein residue position."),
]

#: A batch of 1-based protein residue positions (e.g. for compare_positions).
PositionsArg = Annotated[
    list[int],
    Field(
        description="A batch of 1-based protein residue positions to compare side by side.",
        examples=[[175, 248, 273]],
    ),
]

#: Page size for paginated list results.
LimitArg = Annotated[
    int,
    Field(
        ge=1,
        le=MAX_PAGE_LIMIT,
        description=f"Maximum rows to return (1..{MAX_PAGE_LIMIT}; default {DEFAULT_PAGE_LIMIT}).",
    ),
]

#: Zero-based row offset into a paginated list result.
OffsetArg = Annotated[
    int,
    Field(ge=0, description="Zero-based offset into the result list (for paging)."),
]

#: Variant-source selector for per-position counts.
SourceArg = Annotated[
    Literal["both", "gnomad", "clinvar"],
    Field(description="Variant source to report: both|gnomad|clinvar (default both)."),
]
