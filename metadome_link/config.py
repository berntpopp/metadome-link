"""Configuration management for metadome-link.

Settings load from environment variables with the ``METADOME_LINK_`` prefix
(nested models use ``__``, e.g. ``METADOME_LINK_METADOME__BASE_URL=...``) and an
optional ``.env`` file.

metadome-link is a **live-API proxy**: it calls the MetaDome web service over
async httpx and caches completed landscapes on disk. There is no local bulk
index / ingest step.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InsecureBindError(RuntimeError):
    """A non-loopback bind was requested without the explicit public-bind opt-in."""


def is_loopback_host(host: str) -> bool:
    """Return True if binding ``host`` exposes only the loopback interface.

    ``localhost`` and any address in ``127.0.0.0/8`` or ``::1`` are loopback. The
    wildcard binds (``0.0.0.0`` / ``::``) and every routable address are NOT.
    """
    candidate = host.strip().lower()
    if candidate == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        # Any other hostname (empty, a public DNS name) is treated as non-loopback.
        return False


def check_bind_safety(host: str, *, allow_public: bool, logger: Any = None) -> None:
    """Fail-closed guard for the direct-run bind interface (F-04).

    metadome-link is **unauthenticated by design** and must sit behind the router
    / reverse proxy. A loopback bind is always safe. A non-loopback bind requires
    the explicit ``METADOME_LINK_ALLOW_PUBLIC_BIND`` opt-in: without it startup is
    refused (``InsecureBindError``); WITH it the server still emits a loud warning
    so the exposure is audited.
    """
    if is_loopback_host(host):
        return
    if not allow_public:
        raise InsecureBindError(
            f"Refusing to bind non-loopback interface {host!r}: metadome-link is "
            "unauthenticated and must sit behind the router/reverse proxy. Bind "
            "127.0.0.1, or set METADOME_LINK_ALLOW_PUBLIC_BIND=true to opt in "
            "(only when a trusted proxy terminates access in front of it)."
        )
    if logger is not None:
        logger.warning(
            f"INSECURE PUBLIC BIND: binding the non-loopback interface {host!r} with "
            "METADOME_LINK_ALLOW_PUBLIC_BIND=true. This unauthenticated backend is "
            "now reachable off-host; ensure a trusted reverse proxy terminates "
            "access in front of it."
        )


class MetaDomeSettings(BaseModel):
    """Upstream MetaDome web-API client settings (base URL, timeouts, poll, politeness)."""

    base_url: str = Field(
        default="https://stuart.radboudumc.nl/metadome/api",
        description="Base URL of the MetaDome web API (no auth required).",
    )
    request_timeout_s: float = Field(
        default=30.0,
        gt=0,
        description="Per-request HTTP timeout (seconds).",
    )
    poll_soft_deadline_s: float = Field(
        default=20.0,
        gt=0,
        description="Max wall-clock seconds a poll loop may spend before returning 'processing'.",
    )
    poll_initial_interval_s: float = Field(
        default=2.0,
        gt=0,
        description="Initial inter-poll sleep (seconds); backs off toward poll_max_interval_s.",
    )
    poll_max_interval_s: float = Field(
        default=8.0,
        gt=0,
        description="Maximum inter-poll sleep (seconds).",
    )
    politeness_rate_per_s: float = Field(
        default=3.0,
        gt=0,
        description="Token-bucket refill rate (requests/second) for upstream politeness.",
    )
    politeness_burst: int = Field(
        default=5,
        ge=1,
        description="Token-bucket burst capacity (max queued requests).",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Max retries on retryable upstream failures (429/5xx/timeout).",
    )
    max_response_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        description=(
            "Hard cap (bytes) on an upstream response body. Exceeding it raises a "
            "non-retryable error (fail-closed, never truncate). Default 64 MiB is "
            "above titin-scale /result/ landscapes."
        ),
    )


class CacheSettings(BaseModel):
    """On-disk result cache + in-memory TTL/LRU settings."""

    db_path: str = Field(
        default="data/metadome_cache.sqlite",
        description="Path to the SQLite result-cache database (parent dir is created).",
    )
    ttl_transcripts_s: int = Field(
        default=21600,
        ge=0,
        description="TTL (seconds) for cached /get_transcripts lists (default 6 h).",
    )
    lru_results: int = Field(
        default=64,
        ge=0,
        description="In-memory LRU size for completed landscapes (in front of the disk cache).",
    )
    lru_transcripts: int = Field(
        default=256,
        ge=0,
        description="In-memory LRU size for transcript lists.",
    )


class ServerSettings(BaseSettings):
    """Top-level server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="METADOME_LINK_",
        env_nested_delimiter="__",
    )

    host: str = Field(
        default="127.0.0.1",
        description="Server bind host (loopback by default; see allow_public_bind).",
    )
    allow_public_bind: bool = Field(
        default=False,
        description=(
            "Opt in to a non-loopback (public) bind. Without it a non-loopback host "
            "is refused at startup: metadome-link is unauthenticated and must sit "
            "behind the router/reverse proxy."
        ),
    )
    port: int = Field(default=8000, ge=1024, le=65535, description="Server port.")

    transport: Literal["unified", "http", "stdio"] = Field(
        default="unified",
        description="Server transport mode.",
    )
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path.")
    allowed_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1", "::1"],
        description="Exact HTTP Host allowlist.",
    )
    allowed_origins: list[str] = Field(default=[], description="Exact HTTP Origin allowlist.")

    cors_origins: list[str] = Field(
        default=[],
        description="Allowed CORS origins.",
    )

    log_level: str = Field(default="INFO", description="Logging level.")
    log_format: Literal["json", "console"] = Field(
        default="console",
        description="Log format.",
    )

    metadome: MetaDomeSettings = Field(
        default_factory=MetaDomeSettings,
        description="Upstream MetaDome web-API client configuration.",
    )
    cache: CacheSettings = Field(
        default_factory=CacheSettings,
        description="Result-cache configuration.",
    )

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure the MCP path starts with a forward slash."""
        return v if v.startswith("/") else f"/{v}"

    @field_validator("allowed_hosts", "allowed_origins")
    @classmethod
    def reject_allowlist_wildcards(cls, values: list[str]) -> list[str]:
        """Require exact entries because FastMCP supports glob matching."""
        if any(character in entry for entry in values for character in "*?[]"):
            raise ValueError("wildcard entries are not permitted in HTTP allowlists")
        return values

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from a comma-separated string or a list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return list(v) if v else []


settings = ServerSettings()
