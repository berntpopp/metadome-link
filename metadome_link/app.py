"""FastAPI host for metadome-link (thin: health + service info).

The FastAPI layer is intentionally minimal — the MCP plane carries the tool
surface. ``GET /health`` is the liveness/readiness probe and reports the pinned
MetaDome ``data_versions`` plus the discovery ``capabilities_version`` so deploy
checks (and the router) can confirm which contract is live without a tool call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp.server.http import HostOriginGuardMiddleware

from metadome_link import __version__
from metadome_link.buildinfo import build_info
from metadome_link.config import settings
from metadome_link.constants import DATA_VERSIONS
from metadome_link.mcp.capabilities import capabilities_version

if TYPE_CHECKING:
    pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="metadome-link",
        description=(
            "Read-only MCP/API server wrapping the MetaDome web service "
            "(per-position missense tolerance landscapes, Pfam domains, "
            "meta-domain homolog variant aggregation)."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Container Hardening Standard v1: never combine wildcard origins with
    # credentials. Browsers reject "*" + credentials and it is a security
    # footgun, so disable credentials whenever a wildcard origin is configured.
    allow_credentials = "*" not in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(
        HostOriginGuardMiddleware,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.allowed_origins,
        mode="strict",
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness probe reporting pinned data + capabilities versions."""
        return {
            "status": "ok",
            "version": __version__,
            "transport": "streamable-http-stateless",
            "data_versions": DATA_VERSIONS,
            "capabilities_version": capabilities_version(),
        }

    @app.get("/")
    async def root() -> dict[str, Any]:
        """Service information."""
        return {
            "name": "metadome-link",
            "version": __version__,
            "data_source": "MetaDome (www.metadome.app/metadome)",
            "mcp_endpoint": settings.mcp_path,
            "docs": "/docs",
            "health": "/health",
            **build_info(),
        }

    return app


app = create_app()
