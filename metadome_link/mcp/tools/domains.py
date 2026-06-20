"""Domain tools (``get_protein_domains``, ``get_meta_domain``).

STUB: the concrete tools are registered in Task 12. This no-op keeps the facade
importable and buildable in the meantime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_domain_tools(mcp: FastMCP) -> None:
    """Register the domain tools on a FastMCP instance (no-op stub, Task 12)."""
    return None
