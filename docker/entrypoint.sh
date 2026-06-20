#!/usr/bin/env bash
# Start the metadome-link unified server.
#
# metadome-link is a pure API proxy: there is NO bulk data to download and NO
# index to bootstrap. The SQLite result cache is populated lazily from the live
# MetaDome API at request time and persisted in DATA_DIR across restarts.
#
# This script:
#   1. Ensures the data directory exists and is writable.
#   2. exec's the unified server (FastAPI /health + MCP /mcp on one port),
#      making it PID 1 so it receives SIGTERM/SIGINT for graceful shutdown.
set -euo pipefail

DATA_DIR="${METADOME_LINK_CACHE__DB_PATH:-/app/data/metadome_cache.sqlite}"
DATA_DIR="$(dirname "${DATA_DIR}")"

echo "[entrypoint] Data directory: ${DATA_DIR}"
mkdir -p "${DATA_DIR}"

echo "[entrypoint] Starting metadome-link unified server..."

# exec so the server is PID 1 and receives SIGTERM/SIGINT for graceful shutdown.
exec metadome-link \
    --transport "${METADOME_LINK_TRANSPORT:-unified}" \
    --host "${METADOME_LINK_HOST:-0.0.0.0}" \
    --port "${METADOME_LINK_PORT:-8000}"
