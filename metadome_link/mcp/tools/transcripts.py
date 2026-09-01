"""Transcript-resolution tools (``resolve_transcript``).

Resolves a free-text gene symbol or versioned ENST id to MetaDome transcript
candidate(s). Gene queries are sorted by ``aa_length`` descending and an analyzable
MANE Select transcript is preferred as ``canonical`` (otherwise the longest
analyzable protein-coding transcript). A bare ENST id is validated and echoed.

After a successful gene resolution, ``_meta.next_commands`` includes
``request_tolerance_landscape`` for the canonical transcript, steering the
client straight into the two-step landscape workflow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from metadome_link.mcp import schemas as output_schemas
from metadome_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from metadome_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from metadome_link.mcp.next_commands import cmd
from metadome_link.mcp.service_adapters import get_metadome_service
from metadome_link.mcp.tools._common import GeneOrIdArg, ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP


def after_resolve_transcript(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ``next_commands`` for a successful ``resolve_transcript`` response.

    - **Gene path**: suggests ``request_tolerance_landscape`` for the canonical
      transcript (the preferred analyzable MANE Select entry), followed by
      ``get_tolerance_landscape`` so the client can start the poll loop right away.
    - **ID path**: same, using the echoed transcript id directly.
    - **Not analyzable**: a gene whose transcripts all have
      ``has_protein_data=false`` cannot be built, so suggest no build step.
    - Falls back to ``get_server_capabilities`` if no usable id is found.
    """
    # Not-analyzable gene (no protein-coding transcript): do not suggest a build
    # that is guaranteed to fail upstream.
    if payload.get("analyzable") is False:
        return [cmd("get_server_capabilities")]
    # Gene path: canonical_transcript_id is set
    canonical = payload.get("canonical_transcript_id")
    if canonical:
        return [
            cmd("request_tolerance_landscape", transcript_id=canonical),
            cmd("get_tolerance_landscape", transcript_id=canonical),
        ]
    # ID path: transcript_id is echoed
    tid = payload.get("transcript_id")
    if tid:
        return [
            cmd("request_tolerance_landscape", transcript_id=tid),
            cmd("get_tolerance_landscape", transcript_id=tid),
        ]
    return [cmd("get_server_capabilities")]


def register_transcript_tools(mcp: FastMCP) -> None:
    """Register the transcript tools on a FastMCP instance."""

    @mcp.tool(
        name="resolve_transcript",
        title="Resolve Gene or Transcript ID",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=output_schemas.RESOLVE_TRANSCRIPT_SCHEMA,
        tags={"transcripts"},
        description=(
            "Resolve a gene or transcript to a canonical transcript; "
            "Signature: resolve_transcript(query, response_mode=)."
        ),
    )
    async def resolve_transcript(
        query: GeneOrIdArg,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            service = get_metadome_service()
            payload = await service.resolve_transcript(query, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_resolve_transcript(payload)
            return payload

        return await run_mcp_tool(
            "resolve_transcript",
            call,
            context=McpErrorContext(
                "resolve_transcript",
                arguments={"query": query, "response_mode": response_mode},
                response_mode=response_mode,
            ),
        )
