"""Analysis tools: ``summarize_intolerant_regions``.

Registers one tool on the FastMCP instance: ``summarize_intolerant_regions``,
which identifies the most constrained contiguous protein regions in a MetaDome
tolerance landscape, annotates each run with overlapping Pfam domain ids, and
separates true ClinVar annotations from Pfam homolog aggregates per region.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, StrictInt

from metadome_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from metadome_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from metadome_link.mcp.next_commands import cmd
from metadome_link.mcp.service_adapters import get_metadome_service
from metadome_link.mcp.tools._common import ResponseMode, ThresholdArg, TranscriptIdArg

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _after_summarize(
    transcript_id: str,
    regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build next_commands hints for a successful summarize result.

    Suggests drilling into the most intolerant region with ``get_position_tolerance``
    (using the midpoint of the first ranked region) and ``get_meta_domain`` for the
    same position, plus the full landscape as a broad follow-on.
    """
    steps: list[dict[str, Any]] = []
    if regions:
        top = regions[0]
        midpoint = (top["start"] + top["stop"]) // 2
        steps.append(
            cmd(
                "get_position_tolerance",
                transcript_id=transcript_id,
                position=midpoint,
            )
        )
        steps.append(
            cmd(
                "get_meta_domain",
                transcript_id=transcript_id,
                position=midpoint,
            )
        )
    steps.append(
        cmd(
            "get_tolerance_landscape",
            transcript_id=transcript_id,
        )
    )
    return steps


def register_analysis_tools(mcp: FastMCP) -> None:
    """Register the analysis tools on a FastMCP instance."""

    @mcp.tool(
        name="summarize_intolerant_regions",
        title="Summarize Intolerant Regions",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"analysis"},
        description=(
            "Return the top ranked contiguous intolerant regions of a MetaDome tolerance "
            "landscape, each annotated with overlapping Pfam domain ids and explicitly scoped "
            "variant evidence. Regions are stretches of consecutive residues "
            "with sw_dn_ds below `threshold` (length >= `min_run`), ranked by mean "
            "sw_dn_ds ascending (most constrained first). "
            "Signature: summarize_intolerant_regions(transcript_id, threshold=0.5, "
            "min_run=3, top_n=15, response_mode='compact')."
        ),
    )
    async def summarize_intolerant_regions(
        transcript_id: TranscriptIdArg,
        threshold: ThresholdArg = 0.5,
        min_run: Annotated[
            StrictInt,
            Field(
                ge=1,
                le=100,
                description=(
                    "Minimum number of consecutive residues to form a region (default 3). "
                    "Shorter stretches are discarded."
                ),
            ),
        ] = 3,
        top_n: Annotated[
            StrictInt,
            Field(
                ge=1,
                le=100,
                description=(
                    "Maximum number of regions to return, ranked by mean_sw_dn_ds ascending "
                    "(default 15)."
                ),
            ),
        ] = 15,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        service = get_metadome_service()

        async def call() -> dict[str, Any]:
            payload = await service.summarize_intolerant_regions(
                transcript_id,
                threshold=threshold,
                min_run=min_run,
                top_n=top_n,
                response_mode=response_mode,
            )
            regions: list[dict[str, Any]] = payload.get("regions", [])
            payload.setdefault("_meta", {})["next_commands"] = _after_summarize(
                str(payload.get("transcript_id", transcript_id)),
                regions,
            )
            return payload

        return await run_mcp_tool(
            "summarize_intolerant_regions",
            call,
            context=McpErrorContext(
                "summarize_intolerant_regions",
                arguments={"transcript_id": transcript_id},
                response_mode=response_mode,
            ),
        )
