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

RUN pip install --upgrade pip uv && \
    uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    METADOME_LINK_TRANSPORT=unified \
    METADOME_LINK_HOST=0.0.0.0 \
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
    CMD curl -f http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
