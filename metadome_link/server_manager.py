"""Unified server manager for HTTP, stdio, and unified (HTTP+MCP) transports.

The manager owns the *running* server's single :class:`MetaDomeService`: it is
built ONCE from a real :class:`MetaDomeClient` + :class:`ResultCache`, registered
process-wide via :func:`set_metadome_service`, and torn down on shutdown
(``client.aclose()`` + ``cache.close()``). Unlike a bulk-index server there is no
ingest/bootstrap step — completed landscapes warm the on-disk cache lazily.

In *unified* mode the FastMCP ASGI app (``mcp.http_app(path=settings.mcp_path)``)
is mounted under the FastAPI app on a single port; the two lifespans are combined
so the MCP session manager starts/stops with the host. In *stdio* mode the same
service is registered and FastMCP serves JSON-RPC over stdin/stdout — with the
banner suppressed, since stray stdout bytes corrupt the framing.
"""

from __future__ import annotations

import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any

import uvicorn

from metadome_link.api.client import MetaDomeClient
from metadome_link.cache.store import ResultCache
from metadome_link.config import check_bind_safety, settings
from metadome_link.mcp.facade import create_metadome_mcp
from metadome_link.mcp.service_adapters import set_metadome_service
from metadome_link.services.metadome_service import MetaDomeService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from structlog.typing import FilteringBoundLogger


class UnifiedServerManager:
    """Orchestrate startup of metadome-link in any transport mode."""

    def __init__(self, logger: FilteringBoundLogger | None = None) -> None:
        """Build a manager with an optional structlog logger."""
        self.logger = logger
        self._uvicorn_server: uvicorn.Server | None = None
        self._client: MetaDomeClient | None = None
        self._cache: ResultCache | None = None

    # -- service lifecycle -----------------------------------------------------

    def _build_service(self) -> MetaDomeService:
        """Construct the single live service (client + cache) and register it."""
        self._client = MetaDomeClient(settings)
        self._cache = ResultCache(db_path=settings.cache.db_path)
        service = MetaDomeService(self._client, self._cache, settings=settings)
        set_metadome_service(service)
        return service

    async def _teardown_service(self) -> None:
        """Close the upstream client + result cache and clear the registry."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._cache is not None:
            self._cache.close()
            self._cache = None
        set_metadome_service(None)

    # -- transports ------------------------------------------------------------

    async def start_unified_server(self, host: str, port: int) -> None:
        """Start FastAPI + MCP (streamable-http) on the same port."""
        # F-04: fail-closed at the actual bind site — every path that binds an
        # interface is guarded here, not only the server.py entry point. Refuses
        # a non-loopback host unless METADOME_LINK_ALLOW_PUBLIC_BIND is set;
        # warns loudly when the opt-in is used. Raises BEFORE any bind.
        check_bind_safety(host, allow_public=settings.allow_public_bind, logger=self.logger)
        if self.logger:
            self.logger.info(
                "Starting unified server", host=host, port=port, mcp_path=settings.mcp_path
            )

        from metadome_link.app import app as fastapi_app

        self._build_service()
        mcp = create_metadome_mcp()
        mcp_asgi = mcp.http_app(
            path=settings.mcp_path,
            stateless_http=True,
            json_response=True,
            host_origin_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=settings.allowed_origins,
        )

        original_lifespan = fastapi_app.router.lifespan_context

        @asynccontextmanager
        async def combined_lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(original_lifespan(app))
                await stack.enter_async_context(mcp_asgi.router.lifespan_context(app))
                try:
                    yield
                finally:
                    await self._teardown_service()

        fastapi_app.router.lifespan_context = combined_lifespan
        fastapi_app.mount("/", mcp_asgi)

        config = uvicorn.Config(
            app=fastapi_app, host=host, port=port, log_config=None, lifespan="on"
        )
        self._uvicorn_server = uvicorn.Server(config)
        await self._uvicorn_server.serve()

    async def start_http_only_server(self, host: str, port: int) -> None:
        """Start FastAPI only (no MCP)."""
        # F-04: fail-closed at the actual bind site (see start_unified_server).
        check_bind_safety(host, allow_public=settings.allow_public_bind, logger=self.logger)
        if self.logger:
            self.logger.info("Starting HTTP-only server", host=host, port=port)

        from metadome_link.app import app as fastapi_app

        self._build_service()
        original_lifespan = fastapi_app.router.lifespan_context

        @asynccontextmanager
        async def http_lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with original_lifespan(app):
                try:
                    yield
                finally:
                    await self._teardown_service()

        fastapi_app.router.lifespan_context = http_lifespan

        config = uvicorn.Config(
            app=fastapi_app, host=host, port=port, log_config=None, lifespan="on"
        )
        self._uvicorn_server = uvicorn.Server(config)
        await self._uvicorn_server.serve()

    async def start_stdio_server(self) -> None:
        """Start the FastMCP stdio transport (for Claude Desktop)."""
        self._configure_stdio_environment()
        if self.logger:
            self.logger.info("Starting stdio MCP server")

        self._build_service()
        try:
            mcp = create_metadome_mcp()
            # show_banner=False is critical: stray stdout bytes corrupt JSON-RPC framing.
            await mcp.run_async(transport="stdio", show_banner=False)
        finally:
            await self._teardown_service()

    async def shutdown(self) -> None:
        """Gracefully stop any running server."""
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self.logger:
            self.logger.info("Shutdown complete")

    @staticmethod
    def _configure_stdio_environment() -> None:
        """Suppress non-JSON output that would corrupt stdio MCP framing."""
        env_defaults: dict[str, Any] = {
            "PYTHONUNBUFFERED": "1",
            "METADOME_LINK_TRANSPORT": "stdio",
            "FASTMCP_DISABLE_BANNER": "1",
            "FASTMCP_QUIET": "1",
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
            "TERM": "dumb",
            "PYTHONWARNINGS": "ignore",
        }
        for key, value in env_defaults.items():
            os.environ.setdefault(key, value)
