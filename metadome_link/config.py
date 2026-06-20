"""Configuration management for metadome-link.

Settings load from environment variables with the ``METADOME_LINK_`` prefix
(nested models use ``__``, e.g. ``METADOME_LINK_METADOME__BASE_URL=...``) and an
optional ``.env`` file.

metadome-link is a **live-API proxy**: it calls the MetaDome web service over
async httpx and caches completed landscapes on disk. There is no local bulk
index / ingest step.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    host: str = Field(default="0.0.0.0", description="Server host.")  # noqa: S104
    port: int = Field(default=8000, ge=1024, le=65535, description="Server port.")

    transport: Literal["unified", "http", "stdio"] = Field(
        default="unified",
        description="Server transport mode.",
    )
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path.")

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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from a comma-separated string or a list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return list(v) if v else []


settings = ServerSettings()
