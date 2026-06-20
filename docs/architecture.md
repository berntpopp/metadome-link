# Architecture

`metadome-link` is split into **two planes** that communicate through a thin envelope boundary.
This pattern is shared across the GeneFoundry `-link` fleet.

## Two-plane design

### Data plane

The data plane (`config`, `constants`, `identifiers`, `exceptions`, `api/`, `cache/`,
`services/`) calls the MetaDome web API over async httpx, normalizes responses, and returns
**plain dicts**. It raises **typed exceptions** from `metadome_link.exceptions`; it never
builds response envelopes.

```
metadome_link/
  config.py          # pydantic-settings, prefix METADOME_LINK_, nested MetaDomeSettings + CacheSettings
  constants.py       # pinned versions, citations, caveats, limits, ENST_RE
  identifiers.py     # normalize_gene_symbol, validate_transcript_id (requires .N version)
  exceptions.py      # MetaDomeError + 7 subclasses (7-code taxonomy)

  api/
    client.py        # async MetaDomeClient: 6 endpoints + poll_until_ready loop
    models.py        # TypedDicts for TranscriptSummary, LandscapePosition, Domain

  cache/
    store.py         # ResultCache (SQLite) + TTLCache (in-memory) + metadome-link-cache CLI

  services/
    metadome_service.py  # orchestrates client + cache → plain dicts
    resolution.py        # sort/canonical helpers for transcript lists
    landscape.py         # slice_positions, intolerant_runs, position_to_entry, domains_for_position
    pagination.py        # paginate(items, limit, offset) → (page, block)
    shaping.py           # shape_record(record, mode) for 4 response_mode tiers
    citation.py          # recommended_citation builder (verbatim Wiel 2019)
```

Unlike most fleet siblings there is **no `ingest/` step and no local SQLite index of all data**.
MetaDome has no bulk dump; the data plane is a **live-API proxy + persistent result cache**
(the gtex-link / mavedb-link pattern).

### MCP plane

The MCP plane (`mcp/`) is domain-agnostic scaffolding lifted from `mondo-link`.
`run_mcp_tool` (in `mcp/envelope.py`) owns `success` / `_meta` and converts typed
exceptions into **returned** structured error payloads (never raised to the client).

```
metadome_link/mcp/
  facade.py          # create_metadome_mcp() → FastMCP (instructions, middleware, register_*)
  envelope.py        # run_mcp_tool(), McpErrorContext, McpToolError, classify_exception()
  capabilities.py    # build_capabilities(), capabilities_version(), register_capability_resources()
  resources.py       # METADOME_SERVER_INSTRUCTIONS, METADOME_USAGE_NOTES, METADOME_REFERENCE_NOTES
  annotations.py     # READ_ONLY_OPEN_WORLD ToolAnnotations
  schemas.py         # one JSON Schema dict per tool (11 total)
  next_commands.py   # cmd() + after_* builders for _meta.next_commands chaining
  middleware.py      # ArgValidationMiddleware
  metrics.py         # in-process latency/req/err counters → get_diagnostics
  service_adapters.py# get/set_metadome_service() DI registry

  tools/
    _common.py       # shared Annotated arg types (ResponseMode, TranscriptIdArg, PositionArg, ...)
    discovery.py     # get_server_capabilities, get_diagnostics
    transcripts.py   # resolve_transcript
    landscape.py     # request_tolerance_landscape, get_tolerance_landscape
    positions.py     # get_position_tolerance, get_variant_counts, compare_positions
    domains.py       # get_protein_domains, get_meta_domain
    analysis.py      # summarize_intolerant_regions
```

## Async request + poll model

MetaDome builds tolerance landscapes asynchronously (Celery task queue). Popular transcripts
(e.g. TP53) are pre-built and return `status:"ready"` immediately. A cold build can take up
to ~1 hour.

The tool surface implements an explicit **request + poll split**:

```
request_tolerance_landscape(transcript_id)
  → submit (POST /submit_visualization/)
  → one status check (GET /status/<tid>/)
  → returns {job_id, status:"ready"|"processing", poll_after_s, eta_hint, cold_build_warning}

get_tolerance_landscape(transcript_id, ...)
  → check disk cache first
  → on cache miss: poll_until_ready(soft_deadline_s=20)
     ├── "ready"      → cache.put_result() → return landscape
     ├── "processing" → return {success:true, status:"processing", poll_after_s}   ← NOT an error
     └── "failed"     → raise UpstreamUnavailableError (returned as upstream_unavailable)
```

The `poll_until_ready` loop is bounded by `METADOME_LINK_METADOME__POLL_SOFT_DEADLINE_S`
(default 20 s): it never blocks indefinitely. Between polls the loop sleeps with exponential
backoff (initial→max interval) and a token-bucket politeness limiter.

## Caching model

| Layer | Scope | Storage | Eviction |
|-------|-------|---------|----------|
| In-memory LRU | Completed landscapes (64 slots) | RAM | LRU eviction |
| On-disk SQLite | Completed landscapes | `data/metadome_cache.sqlite` | Permanent (per `metadome_data_version`) |
| In-memory TTL | Transcript lists | RAM | Time-based (default 6 h) |

Cache keys include `metadome_data_version` (`gencode19-gnomad2.0.2-clinvar20180603-pfam30-app1.0.1`)
so a MetaDome upstream update automatically invalidates stale entries when the constant is bumped.

`/status` is **never cached** — always fetched live.

## Error taxonomy (7 codes)

All errors are **returned** (not raised) as a structured envelope:

```json
{
  "success": false,
  "error_code": "<code>",
  "message": "...",
  "retryable": false,
  "recovery_action": "...",
  "_meta": { "tool": "...", "request_id": "...", "next_commands": [...] }
}
```

| Code | Condition |
|------|-----------|
| `invalid_input` | Bad/unversioned transcript id, out-of-range position, field validation failure |
| `not_found` | Unknown gene symbol, landscape not yet built (recovery: request → get landscape) |
| `ambiguous_query` | Query matches multiple candidates (returns `candidates` list) |
| `data_unavailable` | Data source temporarily unreachable or empty |
| `rate_limited` | Upstream 429 (retryable) |
| `upstream_unavailable` | 5xx / timeout / Celery FAILURE (retryable) |
| `internal_error` | Unexpected server-side error |

## Response envelope

Every tool response follows the same envelope:

```json
{
  "<domain fields>": "...",
  "recommended_citation": "...",       ← on record-derived payloads
  "success": true,
  "_meta": {
    "tool": "...",
    "request_id": "...",
    "data_versions": { "assembly": "GRCh37", "gnomad": "r2.0.2", ... },
    "capabilities_version": "...",     ← compact+
    "next_commands": [ ... ],          ← compact+
    "elapsed_ms": 42                   ← standard/full only
  }
}
```

`_meta` verbosity is tiered by `response_mode`:
- **minimal**: `{tool, request_id}` only.
- **compact** (default): adds `next_commands` + `capabilities_version` + `data_versions`.
- **standard / full**: adds `elapsed_ms`.

## `capabilities_version`

`capabilities_version` is a sha256[:16] content hash of the discovery contract (excluding
`build` and self), keyed by `METADOME_DATA_VERSION`. It is stable across restarts for the
same server version; a warm client compares it to skip re-fetching capabilities.

## Server entry points

| Entry point | Transport | Purpose |
|-------------|-----------|---------|
| `metadome-link` (`server.py:main`) | unified / http / stdio (argparse) | General-purpose server with transport switch |
| `metadome-link-mcp` (`mcp_server.py:main`) | stdio only | Claude Desktop / Claude Code |
| `metadome-link-cache` (`metadome_link.cache.store:main`) | CLI | Cache status / clear / warm |

Unified mode mounts the MCP Streamable-HTTP ASGI app under FastAPI on one port:
`FastAPI(/health) + MCP(/mcp)` — the same pattern the router uses to proxy `/mcp`.
