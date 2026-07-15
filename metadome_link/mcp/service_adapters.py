"""Process-wide dependency-injection registry for the MetaDome service.

The MCP tool surface resolves its service through :func:`get_metadome_service`.
The running server registers a concrete ``MetaDomeService`` (built from a real
``MetaDomeClient`` + ``ResultCache``) via :func:`set_metadome_service` during
startup; tests inject a fake. If nothing is registered, the registry raises an
:class:`InternalError` (mapped to ``internal`` by the envelope) rather than
returning ``None`` -- the service is a hard dependency for every data tool.

``MetaDomeService`` lands in a later task (``services/metadome_service.py``); this
module is typed against it lazily (``TYPE_CHECKING`` only) so the MCP plane builds
and typechecks before the service module exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metadome_link.exceptions import InternalError

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from metadome_link.services.metadome_service import MetaDomeService

_service: MetaDomeService | None = None


def get_metadome_service() -> MetaDomeService:
    """Return the process-wide :class:`MetaDomeService`.

    Raises:
        InternalError: If no service has been registered (server misconfiguration).
    """
    if _service is None:
        raise InternalError(
            "MetaDome service is not initialised. "
            "The server must call set_metadome_service() during startup.",
            recovery_action="switch_tool",
        )
    return _service


def set_metadome_service(service: MetaDomeService | None) -> None:
    """Register (or clear) the process-wide service. Used by the server and tests."""
    global _service
    _service = service


def reset_metadome_service() -> None:
    """Drop the registered service so the next call must re-register one."""
    global _service
    _service = None
