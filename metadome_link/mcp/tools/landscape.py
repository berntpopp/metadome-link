"""Tolerance-landscape tools (``request_tolerance_landscape``, ``get_tolerance_landscape``).

STUB: the concrete tools are registered in Task 10. This no-op keeps the facade
importable and buildable in the meantime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_landscape_tools(mcp: FastMCP) -> None:
    """Register the landscape tools on a FastMCP instance (no-op stub, Task 10)."""
    return None
