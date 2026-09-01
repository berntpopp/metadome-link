# Docker

```bash
make docker-build       # build the image
make docker-up          # start (unified FastAPI host + mounted MCP HTTP app)
make docker-logs        # follow logs
make docker-down        # stop
```

metadome-link is an **MCP/API proxy with read-only data tools and one explicit
idempotent build trigger**: it fetches tolerance landscapes, protein domain annotations,
and variant counts from the live
[MetaDome web API](https://www.metadome.app/metadome/api) at request time.
The image ships **no pre-built data** — on first boot the server starts
immediately and the SQLite result cache populates lazily as requests arrive.

## How caching works

MetaDome computes tolerance landscapes asynchronously (Celery workers, cold
builds can take up to ~1 hour for large transcripts). metadome-link caches
completed landscapes on disk in `/data/metadome_cache.sqlite` so repeat
requests are instant. The cache is keyed by `(transcript_id, data_version)`;
the data version is selected by `METADOME_LINK_METADOME__GENOME_BUILD` and is fixed to
one of the reviewed profiles (`GRCh37.p13` or `GRCh38.p14`).

## Volume

Mount a named volume at `/data` so the SQLite result cache persists across
container restarts:

```yaml
volumes:
  - metadome-data:/data
```

The entrypoint creates the directory automatically on first boot.

## Ports

The host port defaults to `8000`; override with `METADOME_LINK_HOST_PORT` (e.g.
in `.env.docker`). MCP endpoint: `http://127.0.0.1:<port>/mcp`. Health:
`http://127.0.0.1:<port>/health`.

## Startup time

No bulk download is needed. The healthcheck `start_period` is **30 seconds** —
the server typically binds within a few seconds of container start. Subsequent
restarts reuse the persisted cache and start equally fast.

## Local development

```bash
cp .env.docker.example .env.docker
# edit .env.docker as needed
docker compose -f docker/docker-compose.yml up -d --build
```

## Nginx Proxy Manager (production)

```bash
docker compose -f docker/docker-compose.npm.yml --env-file .env.docker up -d --build
```

The NPM overlay exposes only port 8000 internally (no host port binding),
applies hardened security settings (`read_only`, `cap_drop ALL`,
`no-new-privileges`), and joins the shared external `npm_default` network.
NPM routes `https://metadome-link.yourdomain.com` → `http://metadome-link-npm:8000`.

## Cache management

```bash
make cache-status    # show on-disk cache stats
make cache-clear     # clear the result cache
make cache-warm GENES="TP53 BRCA1"  # pre-warm popular transcripts
```

Or exec into a running container:

```bash
docker compose -f docker/docker-compose.yml exec metadome-link metadome-link-cache status
```
