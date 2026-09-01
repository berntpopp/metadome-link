"""Shared MCP tool annotations (read-only research server)."""

from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=True,
)

#: A compute-STARTING tool: it mutates upstream state (POSTs a build job) so it is
#: NOT read-only, but it is non-destructive and idempotent -- MetaDome dedupes the
#: submission by transcript_id, so re-submitting a built/running transcript is a
#: safe no-op. Used by ``request_tolerance_landscape`` (F-11).
COMPUTE_IDEMPOTENT_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
