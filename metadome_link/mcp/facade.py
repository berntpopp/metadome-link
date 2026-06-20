"""MCP facade for metadome-link: assemble the FastMCP instance with all tools.

:func:`create_metadome_mcp` is the single construction point for the server's MCP
plane. It builds the ``FastMCP`` instance (error details masked), optionally
injects a service via ``service_factory`` (tests pass a respx-backed service; the
running server registers a real ``MetaDomeService`` in its startup), registers
every tool group + the ``metadome://`` resource family, and installs the
arg-validation middleware. Tasks 9-13 fill in the five tool-group stubs; the
facade builds today with only the two discovery tools live.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

from metadome_link.mcp.capabilities import register_capability_resources
from metadome_link.mcp.middleware import ArgValidationMiddleware
from metadome_link.mcp.resources import METADOME_SERVER_INSTRUCTIONS
from metadome_link.mcp.service_adapters import set_metadome_service
from metadome_link.mcp.tools import (
    register_analysis_tools,
    register_discovery_tools,
    register_domain_tools,
    register_landscape_tools,
    register_position_tools,
    register_transcript_tools,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from metadome_link.services.metadome_service import MetaDomeService


def create_metadome_mcp(
    service_factory: Callable[[], MetaDomeService] | None = None,
) -> FastMCP:
    """Build a FastMCP instance with all metadome-link tools, resources, middleware.

    Args:
        service_factory: Optional zero-arg factory; if given, its result is
            registered as the process-wide ``MetaDomeService`` via
            :func:`set_metadome_service`. The running server omits this and
            registers the real service during startup instead.

    Returns:
        A configured :class:`FastMCP` instance ready to serve.
    """
    mcp: FastMCP = FastMCP(
        name="metadome-link",
        instructions=METADOME_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )

    if service_factory is not None:
        set_metadome_service(service_factory())

    register_discovery_tools(mcp)
    register_transcript_tools(mcp)
    register_landscape_tools(mcp)
    register_position_tools(mcp)
    register_domain_tools(mcp)
    register_analysis_tools(mcp)
    register_capability_resources(mcp)

    mcp.add_middleware(ArgValidationMiddleware())

    return mcp
