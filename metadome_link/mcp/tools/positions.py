"""Position tools (``get_position_tolerance``, ``get_variant_counts``, ``compare_positions``).

Fully implemented here (Task 11). All three operate on a *built* tolerance
landscape: they delegate to :class:`~metadome_link.services.metadome_service.MetaDomeService`,
which raises a :class:`~metadome_link.exceptions.NotFoundError`
(``recovery_action="switch_tool"``) when the landscape is not built yet -- the
error boundary then surfaces ``request_tolerance_landscape`` +
``get_tolerance_landscape`` as the recovery ``next_commands``.

Each tool mirrors the canonical pattern in ``discovery.py``: a ``@mcp.tool``
wrapping an inner ``call`` coroutine that returns a plain dict, run through
:func:`~metadome_link.mcp.envelope.run_mcp_tool` for the ``success``/``_meta``
envelope. The success-path ``_meta.next_commands`` are built locally by the
``after_*`` chainers below (e.g. a residue that maps into a meta-domain suggests
``get_meta_domain`` as the obvious next step).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from metadome_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from metadome_link.mcp.envelope import McpErrorContext, run_mcp_tool
from metadome_link.mcp.next_commands import _more_steps, cmd
from metadome_link.mcp.schemas import (
    COMPARE_POSITIONS_SCHEMA,
    GET_POSITION_TOLERANCE_SCHEMA,
    GET_VARIANT_COUNTS_SCHEMA,
)
from metadome_link.mcp.service_adapters import get_metadome_service
from metadome_link.mcp.tools._common import (
    LimitArg,
    OffsetArg,
    PositionArg,
    PositionsArg,
    ResponseMode,
    SourceArg,
    TranscriptIdArg,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _has_metadomain(payload: dict[str, Any]) -> bool:
    """Whether a position payload maps into at least one Pfam (meta-)domain."""
    domains = payload.get("domains")
    if isinstance(domains, dict) and domains:
        return True
    domain_ids = payload.get("domain_ids")
    return bool(isinstance(domain_ids, list) and domain_ids)


def after_position(
    payload: dict[str, Any], transcript_id: str, position: int
) -> list[dict[str, Any]]:
    """Success-path next steps for ``get_position_tolerance``.

    A residue inside a meta-domain leads naturally to ``get_meta_domain`` (the
    aligned homologous-variant view); always offer the variant detail and a
    side-by-side comparison entry point.
    """
    steps: list[dict[str, Any]] = []
    if _has_metadomain(payload):
        steps.append(cmd("get_meta_domain", transcript_id=transcript_id, position=position))
    steps.append(cmd("get_variant_counts", transcript_id=transcript_id, position=position))
    steps.append(cmd("compare_positions", transcript_id=transcript_id, positions=[position]))
    return steps


def after_variant_counts(
    payload: dict[str, Any],
    transcript_id: str,
    *,
    position: int | None,
    position_start: int | None,
    position_stop: int | None,
    source: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Success-path next steps for ``get_variant_counts``."""
    if position is not None:
        return [
            cmd("get_position_tolerance", transcript_id=transcript_id, position=position),
            cmd("get_meta_domain", transcript_id=transcript_id, position=position),
        ]
    steps: list[dict[str, Any]] = []
    pagination = payload.get("pagination")
    if isinstance(pagination, dict):
        base: dict[str, Any] = {
            "transcript_id": transcript_id,
            "source": source,
            "limit": limit,
        }
        if position_start is not None:
            base["position_start"] = position_start
        if position_stop is not None:
            base["position_stop"] = position_stop
        steps.extend(_more_steps("get_variant_counts", base, pagination, ceiling=1000))
    steps.extend(
        [
            cmd("summarize_intolerant_regions", transcript_id=transcript_id),
            cmd("get_tolerance_landscape", transcript_id=transcript_id),
        ]
    )
    return steps


def after_compare(payload: dict[str, Any], transcript_id: str) -> list[dict[str, Any]]:
    """Success-path next steps for ``compare_positions``.

    Drill into the most intolerant compared residue (lowest ``sw_dn_ds``) with
    ``get_position_tolerance`` for the full per-residue context.
    """
    rows = payload.get("comparison")
    best_pos: int | None = None
    best_score: float | None = None
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or "error" in row:
                continue
            score = row.get("sw_dn_ds")
            pos = row.get("protein_pos")
            if (
                isinstance(score, int | float)
                and isinstance(pos, int)
                and (best_score is None or score < best_score)
            ):
                best_score, best_pos = float(score), pos
    if best_pos is not None:
        return [cmd("get_position_tolerance", transcript_id=transcript_id, position=best_pos)]
    return [cmd("get_tolerance_landscape", transcript_id=transcript_id)]


def register_position_tools(mcp: FastMCP) -> None:
    """Register the position tools on a FastMCP instance."""

    @mcp.tool(
        name="get_position_tolerance",
        title="Get Position Tolerance",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=GET_POSITION_TOLERANCE_SCHEMA,
        tags={"positions"},
        description=(
            "Return one residue's missense tolerance (sw_dn_ds + sliding-window coverage), "
            "its Pfam/meta-domain membership, and gnomAD/ClinVar variant counts on a built "
            "tolerance landscape. Out-of-range positions raise invalid_input; a not-yet-built "
            "landscape raises not_found (request_tolerance_landscape first). "
            "Signature: get_position_tolerance(transcript_id=, position=, response_mode=)."
        ),
    )
    async def get_position_tolerance(
        transcript_id: TranscriptIdArg,
        position: PositionArg,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload = await service.get_position(
                transcript_id, position, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_position(
                payload, transcript_id, position
            )
            return payload

        return await run_mcp_tool(
            "get_position_tolerance",
            call,
            context=McpErrorContext(
                "get_position_tolerance",
                response_mode=response_mode,
                arguments={"transcript_id": transcript_id, "position": position},
            ),
        )

    @mcp.tool(
        name="get_variant_counts",
        title="Get Variant Counts",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=GET_VARIANT_COUNTS_SCHEMA,
        tags={"positions"},
        description=(
            "Return per-position gnomAD and/or ClinVar variant counts on a built landscape, "
            "filtered by source (both|gnomad|clinvar). Accepts a single position, a "
            "[position_start, position_stop] range, or the whole protein (paginated); when "
            "source includes clinvar each residue's ClinVar variants are listed with NCBI urls. "
            "Signature: get_variant_counts(transcript_id=, position=, position_start=, "
            "position_stop=, source=, limit=, offset=, response_mode=)."
        ),
    )
    async def get_variant_counts(
        transcript_id: TranscriptIdArg,
        position: Annotated[
            int | None, Field(ge=1, description="A single 1-based residue position.")
        ] = None,
        position_start: Annotated[
            int | None, Field(ge=1, description="Inclusive start of a residue range.")
        ] = None,
        position_stop: Annotated[
            int | None, Field(ge=1, description="Inclusive stop of a residue range.")
        ] = None,
        source: SourceArg = "both",
        limit: LimitArg = 200,
        offset: OffsetArg = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload = await service.get_variant_counts(
                transcript_id,
                position=position,
                position_start=position_start,
                position_stop=position_stop,
                source=source,
                limit=limit,
                offset=offset,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = after_variant_counts(
                payload,
                transcript_id,
                position=position,
                position_start=position_start,
                position_stop=position_stop,
                source=source,
                limit=limit,
            )
            return payload

        return await run_mcp_tool(
            "get_variant_counts",
            call,
            context=McpErrorContext(
                "get_variant_counts",
                response_mode=response_mode,
                arguments={
                    "transcript_id": transcript_id,
                    "source": source,
                    "limit": limit,
                    "offset": offset,
                },
            ),
        )

    @mcp.tool(
        name="compare_positions",
        title="Compare Positions",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=COMPARE_POSITIONS_SCHEMA,
        tags={"positions"},
        description=(
            "Return a side-by-side tolerance table (sw_dn_ds, ref_aa, domain ids, variant "
            "counts) for a batch of residue positions on a built landscape. Out-of-range "
            "positions get a per-item error row -- the whole batch never fails for one bad "
            "position; the batch size is capped. "
            "Signature: compare_positions(transcript_id=, positions=, response_mode=)."
        ),
    )
    async def compare_positions(
        transcript_id: TranscriptIdArg,
        positions: PositionsArg,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload = await service.compare_positions(
                transcript_id, positions, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_compare(payload, transcript_id)
            return payload

        return await run_mcp_tool(
            "compare_positions",
            call,
            context=McpErrorContext(
                "compare_positions",
                response_mode=response_mode,
                arguments={"transcript_id": transcript_id},
            ),
        )
