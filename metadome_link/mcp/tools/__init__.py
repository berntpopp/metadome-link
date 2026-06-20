"""MetaDome MCP tool registrations.

Each ``register_<group>_tools(mcp)`` attaches one functional group of tools to a
FastMCP instance. The facade calls them in canonical order (discovery →
transcripts → landscape → positions → domains → analysis). Discovery is fully
implemented in Task 8; the other five groups are no-op stubs filled in by Tasks
9-13.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metadome_link.mcp.tools.analysis import register_analysis_tools
from metadome_link.mcp.tools.discovery import register_discovery_tools
from metadome_link.mcp.tools.domains import register_domain_tools
from metadome_link.mcp.tools.landscape import register_landscape_tools
from metadome_link.mcp.tools.positions import register_position_tools
from metadome_link.mcp.tools.transcripts import register_transcript_tools

if TYPE_CHECKING:
    from fastmcp import FastMCP

__all__ = [
    "register_all_tools",
    "register_analysis_tools",
    "register_discovery_tools",
    "register_domain_tools",
    "register_landscape_tools",
    "register_position_tools",
    "register_transcript_tools",
]


def register_all_tools(mcp: FastMCP) -> None:
    """Register every tool group on a FastMCP instance in canonical order."""
    register_discovery_tools(mcp)
    register_transcript_tools(mcp)
    register_landscape_tools(mcp)
    register_position_tools(mcp)
    register_domain_tools(mcp)
    register_analysis_tools(mcp)
