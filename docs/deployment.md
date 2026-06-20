# Deployment

## Docker

The image starts the unified server (FastAPI `/health` + MCP `/mcp`) on port 8000
immediately — there is no bulk-ingest step. The result cache warms lazily as landscapes
are requested. Mount a persistent volume at `/app/data` so cached landscapes survive
container restarts.

```bash
# Local dev
make docker-build       # docker build -f docker/Dockerfile -t metadome-link:ci .
make docker-up          # docker compose -f docker/docker-compose.yml up -d
make docker-logs        # follow container logs
make docker-down        # docker compose down

# Production (nginx-proxy-manager overlay)
docker compose -f docker/docker-compose.npm.yml --env-file .env.docker up -d --build
```

The production overlay (`docker-compose.npm.yml`) is self-contained (not layered over the
dev compose). It uses `expose: 8000` only (no host port), `read_only: true`, `tmpfs` scratch,
`security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, resource limits, and dual
networks (internal bridge + external `${NPM_SHARED_NETWORK_NAME:-npm_default}`).

Health check:
```bash
curl http://localhost:8000/health
# → {"status": "ok", "data_versions": {"assembly": "GRCh37", ...}}
```

## Configuration (environment variables)

All settings use the `METADOME_LINK_` prefix; nested models use `__` as the delimiter.
Copy `.env.docker.example` to `.env.docker` and set the values for your deployment.

### Server settings

| Variable | Default | Purpose |
|----------|---------|---------|
| `METADOME_LINK_HOST` | `0.0.0.0` | Bind host (use `127.0.0.1` behind a reverse proxy). |
| `METADOME_LINK_PORT` | `8000` | Bind port. |
| `METADOME_LINK_TRANSPORT` | `unified` | `unified` \| `http` \| `stdio`. |
| `METADOME_LINK_MCP_PATH` | `/mcp` | MCP endpoint mount path (must start with `/`). |
| `METADOME_LINK_CORS_ORIGINS` | `""` | Comma-separated allowed CORS origins. |
| `METADOME_LINK_LOG_LEVEL` | `INFO` | `DEBUG`…`CRITICAL`. Logs go to stderr. |
| `METADOME_LINK_LOG_FORMAT` | `console` | `console` (dev) \| `json` (prod). |

### MetaDome upstream (`METADOME_LINK_METADOME__*`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `METADOME_LINK_METADOME__BASE_URL` | `https://stuart.radboudumc.nl/metadome/api` | MetaDome API base URL. |
| `METADOME_LINK_METADOME__REQUEST_TIMEOUT_S` | `30.0` | Per-request HTTP timeout (s). |
| `METADOME_LINK_METADOME__POLL_SOFT_DEADLINE_S` | `20.0` | Max poll-loop wall time before returning `status:"processing"`. |
| `METADOME_LINK_METADOME__POLL_INITIAL_INTERVAL_S` | `2.0` | Initial poll sleep (s). |
| `METADOME_LINK_METADOME__POLL_MAX_INTERVAL_S` | `8.0` | Maximum inter-poll sleep (s). |
| `METADOME_LINK_METADOME__POLITENESS_RATE_PER_S` | `3.0` | Token-bucket refill rate (req/s). |
| `METADOME_LINK_METADOME__POLITENESS_BURST` | `5` | Token-bucket burst capacity. |
| `METADOME_LINK_METADOME__MAX_RETRIES` | `3` | Retries on 429/5xx/timeout. |

### Cache (`METADOME_LINK_CACHE__*`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `METADOME_LINK_CACHE__DB_PATH` | `data/metadome_cache.sqlite` | On-disk SQLite result cache path. Inside Docker, set to `/app/data/metadome_cache.sqlite`. |
| `METADOME_LINK_CACHE__TTL_TRANSCRIPTS_S` | `21600` | TTL for transcript list cache (default 6 h). |
| `METADOME_LINK_CACHE__LRU_RESULTS` | `64` | In-memory LRU size for completed landscapes. |
| `METADOME_LINK_CACHE__LRU_TRANSCRIPTS` | `256` | In-memory LRU size for transcript lists. |

## Unified transport

In `unified` mode the server mounts the MCP Streamable-HTTP ASGI app alongside the FastAPI
application on one port:

```
:8000
  GET  /health   → FastAPI health endpoint (data_versions, capabilities_version, status)
  *    /mcp      → FastMCP Streamable-HTTP (all 11 tools, metadome:// resources)
```

This is the transport the GeneFoundry router uses — it proxies the `/mcp` endpoint as
`https://metadome-link.genefoundry.org/mcp`.

## GeneFoundry router registration

See [`docs/router-registration.md`](router-registration.md) for the exact `servers.yaml`
entry and environment variable to register this server in the GeneFoundry router.

## Cache management

```bash
# Outside Docker
uv run metadome-link-cache status    # print on-disk stats + pinned data version
uv run metadome-link-cache clear     # delete all cached landscapes
uv run metadome-link-cache warm TP53 BRCA1  # pre-warm popular transcripts

# Inside Docker (exec into running container)
docker exec metadome-link metadome-link-cache status
```

The SQLite cache is keyed `(transcript_id, metadome_data_version)`. When MetaDome ships a new
upstream release, bump `METADOME_DATA_VERSION` in `metadome_link/constants.py` and run
`metadome-link-cache clear` — the server will refetch landscapes on demand.

## Data version pinning

MetaDome data is frozen at `gencode19-gnomad2.0.2-clinvar20180603-pfam30-app1.0.1` (GRCh37,
gnomAD r2.0.2, ClinVar 2018-06-03). This constant (`METADOME_DATA_VERSION`) is the cache key
and also drives `capabilities_version`. Bump it manually in `metadome_link/constants.py`
if MetaDome upstream updates its data version.

## Production checklist

- [ ] Mount a named Docker volume at `/app/data` (cache survives restarts).
- [ ] Set `METADOME_LINK_LOG_FORMAT=json` for structured log ingestion.
- [ ] Set `METADOME_LINK_HOST=0.0.0.0` (default in Docker; use `127.0.0.1` behind a
  reverse proxy without Docker networking).
- [ ] Register the `/mcp` URL in `genefoundry-router` (see `docs/router-registration.md`).
- [ ] Confirm the `/health` endpoint returns 200 before routing traffic.
