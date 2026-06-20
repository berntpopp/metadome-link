"""Analysis tools (``summarize_intolerant_regions``).

STUB: the concrete tool is registered in Task 13. This no-op keeps the facade
importable and buildable in the meantime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_analysis_tools(mcp: FastMCP) -> None:
    """Register the analysis tools on a FastMCP instance (no-op stub, Task 13)."""
    return None
