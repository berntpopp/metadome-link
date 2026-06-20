"""Position tools (``get_position_tolerance``, ``get_variant_counts``, ``compare_positions``).

STUB: the concrete tools are registered in Task 11. This no-op keeps the facade
importable and buildable in the meantime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_position_tools(mcp: FastMCP) -> None:
    """Register the position tools on a FastMCP instance (no-op stub, Task 11)."""
    return None
