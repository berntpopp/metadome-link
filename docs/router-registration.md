# Router Registration

This document describes how to register `metadome-link` in the GeneFoundry router
(`genefoundry-router`). The router is a FastMCP aggregator that proxies each backend's
public HTTPS `/mcp` endpoint and re-exposes tools namespaced as `<namespace>_<tool>`.
**Adding a backend requires three mechanical edits — no router code changes.**

## Step A: `genefoundry-router/servers.yaml`

Append one entry to the `servers:` list. The namespace must match `^[a-z0-9]+$` (`metadome`,
not `metadome-link`):

```yaml
servers:
  # ... existing entries ...
  - name: metadome
    repo: berntpopp/metadome-link
    url_env: GF_METADOME_URL
    namespace: metadome
    tags: [protein, tolerance, domain, variant]
    entrypoints: [resolve_transcript, get_tolerance_landscape]
```

Field notes:
- `name`: human label for logs/display.
- `repo`: GitHub repo (informational; the router does not clone it).
- `url_env`: environment variable that holds the backend's public `/mcp` URL.
- `namespace`: the prefix prepended to all leaf tool names at the router.
  Namespaced names: `metadome_resolve_transcript`, `metadome_get_tolerance_landscape`, etc.
- `tags`: used by `search_tools` BM25 ranking to surface this backend for relevant queries.
- `entrypoints`: un-namespaced canonical front-door tool names. These are **pinned** in the
  router (always listed, bypassing BM25) and named in the router instructions. Only two are
  needed: `resolve_transcript` (discovery + gene resolution) and `get_tolerance_landscape`
  (the primary data fetch after a request).

All unspecified fields inherit from router defaults: `transport: http`, `enabled: true`,
`cache_ttl: 300`.

## Step B: `genefoundry-router/.env` (and `.env.example`, `.env.docker.example`)

Add the backend URL environment variable:

```bash
GF_METADOME_URL=https://metadome-link.genefoundry.org/mcp
```

The router reads this env var at startup and uses the URL to proxy all 11 `metadome-link`
tools. Until the container is deployed and reachable at this URL, you can temporarily set
`enabled: false` in `servers.yaml` or simply omit the env var — the router skips an
unreachable backend with a warning and still starts.

## Step C: Deploy `metadome-link`

Deploy the `metadome-link` container so it is reachable at the URL set in `GF_METADOME_URL`.
The router proxies the `/mcp` Streamable-HTTP endpoint; there is no router-side auth forwarded
(confused-deputy defense). The container must expose port 8000 and serve:

- `GET  /health` → 200 (FastAPI health check)
- `*    /mcp`   → MCP Streamable-HTTP (all 11 tools + `metadome://` resources)

## Verification

After deploying and restarting the router, verify registration with:

```bash
# Validate the servers.yaml schema
genefoundry-router validate

# Confirm the backend is reachable and all tools load
genefoundry-router doctor --strict-naming

# List all tools registered under the metadome namespace
genefoundry-router list-tools --namespace metadome
```

Expected output of `list-tools --namespace metadome` (11 tools):

```
metadome_get_server_capabilities
metadome_get_diagnostics
metadome_resolve_transcript           ← pinned entrypoint
metadome_request_tolerance_landscape
metadome_get_tolerance_landscape      ← pinned entrypoint
metadome_get_position_tolerance
metadome_get_variant_counts
metadome_compare_positions
metadome_get_protein_domains
metadome_get_meta_domain
metadome_summarize_intolerant_regions
```

## Tool naming compliance

All 11 tool leaf names comply with the GeneFoundry Tool-Naming Standard v1:
- `verb_noun` format with canonical verbs (`get_*`, `resolve_*`, `request_*`, `compare_*`,
  `summarize_*`).
- ≤ 50 characters.
- Characters: `[a-z0-9_]`.
- Namespaced form (`metadome_<leaf>`) is ≤ 64 characters.

No `transform:` block is required in `servers.yaml`.
