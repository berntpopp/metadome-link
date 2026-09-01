# Deployment

## Docker

The image starts the unified server (FastAPI `/health` + MCP `/mcp`) on port 8000
immediately — there is no bulk-ingest step. The read-only data tools poll/fetch landscapes
and populate the result cache lazily; only the explicit `request_tolerance_landscape` tool
submits an upstream build. Mount a persistent volume at `/data` so cached landscapes
survive container restarts.

```bash
# Local dev
make docker-build       # docker build -f docker/Dockerfile -t metadome-link:ci .
make docker-up          # docker compose -f docker/docker-compose.yml up -d
make docker-logs        # follow container logs
make docker-down        # docker compose down

# Production (nginx-proxy-manager overlay)
docker compose -f docker/docker-compose.npm.yml --env-file .env.docker up -d --build
```

The base compose file publishes the container's port 8000 on **loopback only**
(`127.0.0.1:${METADOME_LINK_HOST_PORT:-8000}:8000`). Set `METADOME_LINK_HOST_PORT` in
`docker/.env` to move the host port when a sibling `-link` project already holds 8000;
`make docker-url` prints the resulting MCP URL.

The production overlay (`docker-compose.npm.yml`) is self-contained (not layered over the
dev compose). It uses `expose: 8000` only (no host port), `read_only: true`, `tmpfs` scratch,
`security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, resource limits, and dual
networks (internal bridge + external `${NPM_SHARED_NETWORK_NAME:-npm_default}`).

Like every GeneFoundry backend, `metadome-link` is **unauthenticated by design**: the router
owns edge auth at the trust boundary. It MUST be reachable only through the router or a
reverse proxy — never published directly to the internet.

Health check:
```bash
curl http://localhost:8000/health
# → {"status": "ok", "data_versions": {"assembly": "GRCh38.p14", ...}}
```

The health endpoint is an operational REST response; MCP tool responses place the same
build-specific provenance under `_meta.data_versions`. The configured build selects the
complete profile (GRCh37.p13 or GRCh38.p14), including its GENCODE, UniProt, Pfam, gnomAD,
and ClinVar snapshots. Do not represent either profile with a single unqualified
`METADOME_DATA_VERSION` string.

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
| `METADOME_LINK_ALLOWED_HOSTS` | `["localhost","127.0.0.1","::1"]` | Exact HTTP Host allowlist as JSON; wildcards are rejected. |
| `METADOME_LINK_ALLOWED_ORIGINS` | `[]` | Exact browser Origin allowlist as JSON. |
| `METADOME_LINK_CORS_ORIGINS` | `""` | Comma-separated allowed CORS origins. |
| `METADOME_LINK_LOG_LEVEL` | `INFO` | `DEBUG`…`CRITICAL`. Logs go to stderr. |
| `METADOME_LINK_LOG_FORMAT` | `console` | `console` (dev) \| `json` (prod). |

Browser deployments must configure the same exact origins in
`METADOME_LINK_ALLOWED_ORIGINS` and `METADOME_LINK_CORS_ORIGINS`; the strict
transport guard and browser CORS are independent controls.

### MetaDome upstream (`METADOME_LINK_METADOME__*`)

The MetaDome web service is public and needs **no API key or token** — there is no credential
to configure. It is, however, a small academic service: the client is politeness-rate-limited
by a token bucket (default 3.0 req/s, burst 5) with retries on 429/5xx/timeout. Do not raise
`POLITENESS_RATE_PER_S` to work around slowness — a cold landscape build is slow upstream
(Celery), not rate-limited.

| Variable | Default | Purpose |
|----------|---------|---------|
| `METADOME_LINK_METADOME__BASE_URL` | `https://www.metadome.app/metadome/api` | MetaDome API base URL. |
| `METADOME_LINK_METADOME__GENOME_BUILD` | `GRCh38.p14` | Exact namespace: `GRCh37.p13` or `GRCh38.p14`; arbitrary patch levels are rejected. |
| `METADOME_LINK_METADOME__REQUEST_TIMEOUT_S` | `30.0` | Per-request HTTP timeout (s). |
| `METADOME_LINK_METADOME__POLL_SOFT_DEADLINE_S` | `20.0` | Max poll-loop wall time before returning `status:"processing"`. |
| `METADOME_LINK_METADOME__POLL_INITIAL_INTERVAL_S` | `2.0` | Initial poll sleep (s). |
| `METADOME_LINK_METADOME__POLL_MAX_INTERVAL_S` | `8.0` | Maximum inter-poll sleep (s). |
| `METADOME_LINK_METADOME__POLITENESS_RATE_PER_S` | `3.0` | Token-bucket refill rate (req/s). |
| `METADOME_LINK_METADOME__POLITENESS_BURST` | `5` | Strict integer 1..1000; token-bucket burst capacity. |
| `METADOME_LINK_METADOME__MAX_RETRIES` | `3` | Strict integer 0..10; retries on 429/5xx/timeout. |
| `METADOME_LINK_METADOME__MAX_RESPONSE_BYTES` | `67108864` | Strict integer 1..134217728; hard upstream response cap. |

### Cache (`METADOME_LINK_CACHE__*`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `METADOME_LINK_CACHE__DB_PATH` | `data/metadome_cache.sqlite` | On-disk SQLite result cache path. Inside Docker, set to `/data/metadome_cache.sqlite`. |
| `METADOME_LINK_CACHE__TTL_TRANSCRIPTS_S` | `21600` | Strict integer 0..604800; TTL for transcript list cache (0 disables). |
| `METADOME_LINK_CACHE__LRU_RESULTS` | `64` | Strict integer 0..4096; in-memory LRU size for completed landscapes (0 disables). |
| `METADOME_LINK_CACHE__LRU_TRANSCRIPTS` | `256` | Strict integer 0..4096; in-memory LRU size for transcript lists (0 disables). |

### Live integration evidence

The default CI-equivalent suite does not call the public service. To run the six
build-scoped v2 endpoint checks against a real authorized target, set
`METADOME_LINK_LIVE_INTEGRATION=1` and run `make test-integration`; optionally set
`METADOME_LINK_LIVE_BASE_URL`, `METADOME_LINK_LIVE_GENE`, and
`METADOME_LINK_LIVE_TRANSCRIPT_ID`. No captured fixture is treated as live evidence.

## Transports

Three transports, selected with `--transport` or `METADOME_LINK_TRANSPORT`.

| Transport | Serves | MCP endpoint? |
|-----------|--------|---------------|
| `unified` (default) | FastAPI `/health` + MCP `/mcp` on one port | **yes** — `/mcp` |
| `http` | FastAPI/REST **only** | **NO** |
| `stdio` | MCP over stdin/stdout (Claude Desktop) | yes (stdio framing) |

> **Footgun.** `--transport http` is REST/FastAPI-only: it does **not** mount the MCP app, so
> there is no `/mcp` endpoint. An MCP client (or the GeneFoundry router) pointed at an `http`
> server will fail to connect. Use `unified` for MCP over HTTP.

In `unified` mode the server mounts the MCP Streamable-HTTP ASGI app alongside the FastAPI
application on one port:

```
:8000
  GET  /health   → FastAPI health endpoint (data_versions, capabilities_version, status)
  *    /mcp      → FastMCP Streamable-HTTP (all 11 tools, metadome:// resources)
```

This is the transport the GeneFoundry router uses — it proxies the `/mcp` endpoint as
`https://metadome-link.genefoundry.org/mcp`.

## MCP client configuration

**HTTP (Streamable HTTP).** Start the server in `unified` mode, then register the `/mcp` URL:

```bash
uv run metadome-link                    # unified, :8000
claude mcp add --transport http metadome-link --scope user http://127.0.0.1:8000/mcp
```

**Stdio** (Claude Desktop / Claude Code). Uses the dedicated `metadome-link-mcp` entry point;
stdout is reserved for the protocol, so logs go to stderr only:

```json
{
  "mcpServers": {
    "metadome-link": {
      "command": "uv",
      "args": ["run", "metadome-link-mcp"],
      "cwd": "/path/to/metadome-link"
    }
  }
}
```

## GeneFoundry router registration

See [`docs/router-registration.md`](router-registration.md) for the exact `servers.yaml`
entry and environment variable to register this server in the GeneFoundry router.

## Cache management

```bash
# Outside Docker
uv run metadome-link-cache status    # print on-disk stats + pinned data version
uv run metadome-link-cache clear     # delete all cached landscapes
uv run metadome-link-cache warm TP53 BRCA1  # resolve, poll/fetch, and cache completed landscapes

# Inside Docker (exec into running container)
docker exec metadome-link metadome-link-cache status
```

`warm` normalizes and de-duplicates at most 32 gene symbols, uses the configured genome-build
profile and cache limits, and performs read-only resolution plus poll/fetch for each gene. It
does not submit a build; a gene is reported as warmed only after its already-completed landscape
is persisted in the profile-specific SQLite namespace. Unknown genes, upstream errors, and
landscapes still processing at the configured poll deadline are reported as failures; the
command continues with the remaining genes and exits nonzero if any gene failed.

The SQLite cache is keyed `(transcript_id, metadome_data_version)`. When MetaDome ships a new
upstream release, update the corresponding build profile in `metadome_link/constants.py` and
run `metadome-link-cache clear` — the server will refetch landscapes on demand. The
`METADOME_DATA_VERSION` constant is only the backwards-compatible alias for the default
GRCh38 profile; it is not a substitute for the selected build-specific profile.

## Data version pinning

MetaDome supports two reviewed build-specific profiles from the same v2 Zenodo snapshot
([DOI](https://doi.org/10.5281/zenodo.19376150)). GRCh37 uses GENCODE v19 and gnomAD
r2.0.2; GRCh38 uses GENCODE v45 and gnomAD v4.1; both use UniProt 2025_01, Pfam 37.4,
and ClinVar 2025-10-06. Their assembly/build identity remains distinct. GRCh38 is
`metadome2.0-grch38.p14-gencode45-uniprot2025_01-pfam37.4-gnomad4.1-clinvar2025-10-06`
and GRCh37 is
`metadome2.0-grch37.p13-gencode19-uniprot2025_01-pfam37.4-gnomad2.0.2-clinvar2025-10-06`.
The selected profile is the cache key and drives `capabilities_version`; arbitrary build
namespaces are rejected.

## Production checklist

- [ ] Mount a named Docker volume at `/data` (cache survives restarts).
- [ ] Set `METADOME_LINK_LOG_FORMAT=json` for structured log ingestion.
- [ ] Set `METADOME_LINK_HOST=0.0.0.0` (default in Docker; use `127.0.0.1` behind a
  reverse proxy without Docker networking).
- [ ] Register the `/mcp` URL in `genefoundry-router` (see `docs/router-registration.md`).
- [ ] Confirm the `/health` endpoint returns 200 before routing traffic.
