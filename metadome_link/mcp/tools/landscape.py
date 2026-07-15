"""Tolerance-landscape tools: ``request_tolerance_landscape`` + ``get_tolerance_landscape``.

These two implement the explicit async split MetaDome forces on us (Celery cold
builds run up to ~1 h): ``request_tolerance_landscape`` submits/echoes a build
handle, and ``get_tolerance_landscape`` is the cache-first poll that either
returns the built landscape (domains + paginated positions) or a first-class
``status: "processing"`` success state. Each tool projects the matching plain
service dict (:meth:`MetaDomeService.request_landscape` /
:meth:`MetaDomeService.get_landscape`) and steers the ``_meta.next_commands``
chain: request -> get; get(processing) -> poll itself; get(ready) -> the
per-position / domain / analysis tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from metadome_link.mcp.annotations import COMPUTE_IDEMPOTENT_OPEN_WORLD, READ_ONLY_OPEN_WORLD
from metadome_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from metadome_link.mcp.next_commands import _more_steps, cmd
from metadome_link.mcp.service_adapters import get_metadome_service
from metadome_link.mcp.tools._common import (
    LimitArg,
    OffsetArg,
    ResponseMode,
    TranscriptIdArg,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: Optional 1-based protein position bound (``position_start`` / ``position_stop``).
#: The ``Field`` wraps ``int | None`` so the description lands on the PROPERTY, not
#: inside the ``anyOf`` int branch (where FastMCP would not surface it to the model).
_PositionBoundArg = Annotated[
    int | None,
    Field(ge=1, description="1-based protein residue position (inclusive range bound)."),
]


def after_request_landscape(payload: dict[str, Any], transcript_id: str) -> list[dict[str, Any]]:
    """Success chain for a build handle: poll the landscape next."""
    return [cmd("get_tolerance_landscape", transcript_id=transcript_id)]


def after_get_landscape(payload: dict[str, Any], transcript_id: str) -> list[dict[str, Any]]:
    """Success chain for a landscape poll.

    While the job is still building (``status == "processing"``) re-suggest the
    poll tool itself; once ready, page forward (if truncated) then fan out to the
    per-position / domain / analysis tools.
    """
    if payload.get("status") == "processing":
        return [cmd("get_tolerance_landscape", transcript_id=transcript_id)]
    base = {"transcript_id": transcript_id}
    pagination = payload.get("pagination")
    steps: list[dict[str, Any]] = []
    if isinstance(pagination, dict):
        steps.extend(_more_steps("get_tolerance_landscape", base, pagination, ceiling=1000))
    steps.extend(
        [
            cmd("get_position_tolerance", transcript_id=transcript_id, position=1),
            cmd("get_protein_domains", transcript_id=transcript_id),
            cmd("summarize_intolerant_regions", transcript_id=transcript_id),
        ]
    )
    return steps


def register_landscape_tools(mcp: FastMCP) -> None:
    """Register the tolerance-landscape tools on a FastMCP instance."""

    @mcp.tool(
        name="request_tolerance_landscape",
        title="Request Tolerance Landscape",
        # F-11: this POSTs /submit_visualization/ (starts a Celery build) -> NOT
        # read-only. Non-destructive + idempotent (MetaDome dedupes by transcript_id).
        annotations=COMPUTE_IDEMPOTENT_OPEN_WORLD,
        output_schema=None,
        tags={"landscape"},
        description=(
            "Submit (or re-confirm) a MetaDome tolerance-landscape build for a versioned "
            "transcript and return a poll handle. status='ready' means the landscape is "
            "pre-built; status='processing' means a cold build is running (up to ~1 hour) -- "
            "poll get_tolerance_landscape with poll_after_s until it is ready. Idempotent. "
            "Signature: request_tolerance_landscape(transcript_id=, response_mode=)."
        ),
    )
    async def request_tolerance_landscape(
        transcript_id: TranscriptIdArg,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload = await service.request_landscape(transcript_id, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_request_landscape(
                payload, transcript_id
            )
            return payload

        return await run_mcp_tool(
            "request_tolerance_landscape",
            call,
            context=McpErrorContext(
                "request_tolerance_landscape",
                arguments={"transcript_id": transcript_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_tolerance_landscape",
        title="Get Tolerance Landscape",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"landscape"},
        description=(
            "Return the (cache-first) MetaDome tolerance landscape for a built transcript: "
            "Pfam domains plus the paginated per-residue positional_annotation (sw_dn_ds "
            "tolerance, variant counts). Optional position_start/position_stop slice an "
            "inclusive residue range. If the build is still running this returns a "
            "first-class status='processing' success -- poll again after poll_after_s. "
            "Signature: get_tolerance_landscape(transcript_id=, position_start=, "
            "position_stop=, limit=, offset=, response_mode=)."
        ),
    )
    async def get_tolerance_landscape(
        transcript_id: TranscriptIdArg,
        position_start: _PositionBoundArg = None,
        position_stop: _PositionBoundArg = None,
        limit: LimitArg = 200,
        offset: OffsetArg = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload = await service.get_landscape(
                transcript_id,
                position_start=position_start,
                position_stop=position_stop,
                limit=limit,
                offset=offset,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = after_get_landscape(
                payload, transcript_id
            )
            return payload

        return await run_mcp_tool(
            "get_tolerance_landscape",
            call,
            context=McpErrorContext(
                "get_tolerance_landscape",
                arguments={"transcript_id": transcript_id},
                response_mode=response_mode,
            ),
        )
