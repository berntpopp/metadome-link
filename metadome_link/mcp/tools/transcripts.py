"""Transcript-resolution tools (``resolve_transcript``).

STUB: the concrete tool is registered in Task 9. This no-op keeps the facade
importable and buildable in the meantime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_transcript_tools(mcp: FastMCP) -> None:
    """Register the transcript tools on a FastMCP instance (no-op stub, Task 9)."""
    return None
