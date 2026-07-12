# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for metadome-link.
#
# metadome-link is a read-only proxy over the MetaDome web API
# (https://stuart.radboudumc.nl/metadome/api). The image ships NO bulk data —
# the SQLite result cache is populated lazily from the live API at request time
# and persisted in the /app/data volume across container restarts. On first boot
# the entrypoint simply sets up the data directory and starts the unified server.

FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /home/app/web
COPY uv.lock pyproject.toml README.md ./

# F-19: install uv from a digest-pinned image (reproducible) instead of the
# previous unbounded floating pip/uv bootstrap.
COPY --from=ghcr.io/astral-sh/uv:0.8.7@sha256:1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab /uv /usr/local/bin/uv

RUN uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS production


# Runtime identity. The deploy builds from a source checkout rather than pulling a
# registry image, so there is no immutable OCI digest to pin; stamping the exact
# commit into the image is what lets an operator prove the running container was
# built from the revision the router's release inventory pins, instead of trusting
# a moving `main`. VCS_REF is unprefixed on purpose: a <SERVICE>_-prefixed name
# would land in the pydantic settings namespace.
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/berntpopp/metadome-link" \
      org.opencontainers.image.revision="${VCS_REF}"
ENV VCS_REF="${VCS_REF}"

# METADOME_LINK_ALLOW_PUBLIC_BIND=true is the explicit, audited opt-in that the
# F-04 bind guard requires: inside the container the server intentionally binds
# 0.0.0.0, but it is only ever reached via the loopback-published port (base
# compose) or the reverse proxy (prod/npm overlays), never the host's public IP.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    METADOME_LINK_TRANSPORT=unified \
    METADOME_LINK_HOST=0.0.0.0 \
    METADOME_LINK_ALLOW_PUBLIC_BIND=true \
    METADOME_LINK_PORT=8000 \
    METADOME_LINK_MCP_PATH=/mcp \
    METADOME_LINK_CACHE__DB_PATH=/app/data/metadome_cache.sqlite \
    METADOME_LINK_LOG_FORMAT=json

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /app/data && \
    chown -R app:app /app/data /home/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /home/app/web

COPY --chown=app:app ./metadome_link ./metadome_link
COPY --chown=app:app ./mcp_server.py ./server.py ./pyproject.toml ./README.md ./
COPY --chown=app:app ./docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN /opt/venv/bin/pip install . --no-deps && chmod +x /usr/local/bin/entrypoint.sh

USER app

EXPOSE 8000

# The SQLite result cache lives under METADOME_LINK_CACHE__DB_PATH (/app/data).
# Mount a volume here so the cache persists across container restarts.
VOLUME ["/app/data"]

# Short start-period: no bulk download — the server starts immediately.
# The healthcheck confirms /health responds after uvicorn is ready.
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=30s \
    CMD curl -f -H 'Host: localhost' http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
