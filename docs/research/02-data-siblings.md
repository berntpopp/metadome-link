# 02 — Data Siblings Study: `mavedb-link` & `spliceailookup-link`

> Research input for building **`metadome-link`** (MetaDome MCP server: per-protein-position
> missense tolerance scores + meta-domain homologue mapping + Pfam domains + per-position
> gnomAD/ClinVar variant counts).
>
> Two sibling servers were studied at source level:
> - **`/home/bernt-popp/development/mavedb-link`** — the closest *data sibling* (per-variant
>   functional effect scores from MaveDB; a live REST API). Best structural template for the
>   data domain, response envelope, caching, and the optional bundled-SQLite mirror.
> - **`/home/bernt-popp/development/spliceailookup-link`** — the closest *methodology sibling*
>   (reverse-engineered from a web tool with no official API, wrapping slow upstream
>   computation). Best template for reverse-engineering the MetaDome dashboard and handling
>   slow/async upstream jobs.
>
> Both are part of the same `-link` fleet and share a near-identical skeleton:
> `pyproject.toml` (uv) → `<pkg>/config.py` (pydantic-settings) → `<pkg>/api/*` (httpx async
> clients) → `<pkg>/services/*` (caching + shaping) → `<pkg>/mcp/*` (FastMCP facade, tools,
> envelope, capabilities, next_commands) → `tests/` (respx + stub-service). **Mirror this
> skeleton.**

---

## Part A — `mavedb-link` (the data sibling)

### A.1 File tree & how it differs from a generic fleet server

```
mavedb_link/
  app.py  server_manager.py  config.py  constants.py  exceptions.py  identifiers.py
  buildinfo.py  logging_config.py
  api/        client.py                      # async httpx client + TTL/LRU cache
  data/       repository.py  hybrid.py  schema.sql  provenance.py   # << UNIQUE: SQLite mirror
  ingest/     builder.py  parsing.py                                # << UNIQUE: bulk-dump → SQLite
  services/   mavedb_service.py  shaping.py  scores.py  calibration.py
              distribution.py  resolvers.py  search.py  variant_lookup.py
  mcp/        facade.py  envelope.py  schemas.py  capabilities.py  next_commands.py
              middleware.py  metrics.py  annotations.py  arg_help.py  resources.py
              service_adapters.py
              tools/  discovery.py score_sets.py variants.py genes.py
                      experiments.py collections.py resolvers.py _common.py
mcp_server.py  server.py            # stdio + REST entry points
```

**What is NOT in a generic fleet server (lift these ideas for MetaDome):**
- `data/` + `ingest/` — an **optional read-only on-disk SQLite mirror** in front of the live
  API, transparently routed via a `HybridClient` subclass. Designed for the case where the
  upstream offers a bulk dump (MetaDome may expose downloadable per-gene tolerance data).
- `services/` is split into many small modules (`scores`, `calibration`, `distribution`,
  `resolvers`, `variant_lookup`, `search`, `shaping`) because a **LOC budget is enforced**
  (`make lint-loc`, `.loc-allowlist`, `scripts/check_file_size.py`). Plan for the same.
- `mcp/metrics.py` powers a live `get_diagnostics` tool (latency percentiles + counters).

### A.2 Tool catalog (15 tools)

Registered in `mavedb_link/mcp/facade.py::create_mavedb_mcp()` —
`FastMCP(name="mavedb-link", instructions=..., mask_error_details=True)`, seven
`register_*_tools(mcp)` fan-out calls, `mavedb://` resources, and `ArgValidationMiddleware`.
Every tool: `@mcp.tool(name, title, annotations=READ_ONLY_OPEN_WORLD, output_schema=..., tags=...)`,
an async closure → `get_mavedb_service().<method>()`, `_meta.next_commands` via an `after_*`
chainer, all wrapped in `run_mcp_tool(name, call, context=McpErrorContext(...))`.

| Tool | Params | Returns |
|---|---|---|
| `get_server_capabilities` | `detail="summary"\|"full"` | discovery surface (tools, signatures, response modes, workflows, error taxonomy, limits) |
| `get_diagnostics` | — | live `/api/version` reachability + runtime latency percentiles + interpretation |
| `search_score_sets` | `text, targets, target_organism_names, target_types, authors, facet_mode, published=True, limit=25(≤100), offset=0, response_mode="compact"` | `{query, results[], total, returned, limit, offset, truncated, next_offset}` |
| `get_score_set` | `urn, response_mode` | score-set record (title, targets+external IDs, experiment_urn, publications, calibrations, record_url) |
| `get_variant_scores` | `urn, start=0, limit=100(≤1000), drop_na_columns=False, response_mode` | parsed score table `{columns, rows[], calibrations, start/limit/total/truncated/next_start}` |
| `get_variant_score` | `urn, hgvs=None, response_mode` | ONE variant by full URN or score-set-URN+hgvs `{urn, query, resolved_by, match_count, variants[]}` |
| `get_score_distribution` | `urn, score=None, response_mode` | server-side stats `{n, min, max, mean, median, q1, q3, stdev, histogram[10], calibrations}` |
| `get_mapped_variants` | `urn, current_only=True, limit=50(≤500), offset=0, response_mode` | GA4GH VRS alleles `{mapped_variants[], ordering, join_key, pagination}` |
| `get_gene_score_sets` | `symbol, limit=20(≤100), offset=0, response_mode` | gene identity (HGNC) + union of score sets targeting it + coverage block |
| `get_experiment` | `urn, response_mode` | experiment record (child score_set_urns, keywords, publications) |
| `search_experiments` | `text, targets, …, published=True, limit, offset, response_mode` | experiment hits, gene-aware reranked |
| `get_collection` | `urn, limit=100(≤500), offset, response_mode` | curated collection (paged member urns) |
| `find_variant` | `vrs_id=None, variant_urn=None, only_current=True, enrich=True, limit, offset, response_mode` | cross-dataset rollup: one variant across EVERY score set |
| `get_hgvs_validation` | `variant, response_mode` | `{variant, valid, message}` via `POST /hgvs/validate` |
| `get_classified_variants` | `urn, classification=None, calibration_urn=None, limit, offset, response_mode` | variants grouped by calibrated functional class |

**MetaDome analogues** to design from this list: `get_server_capabilities` + `get_diagnostics`
(copy directly); `search`/`resolve_gene` (→ MetaDome by gene symbol / transcript); a
`get_tolerance_landscape(transcript)` (the per-position track, analogous to
`get_variant_scores`); `get_position(transcript, position)` (analogous to `get_variant_score`);
`get_domains(transcript)` (Pfam); `get_meta_domain(transcript, position)` (homologue mapping).

### A.3 Data model

- **No Pydantic response models.** Domain output is **JSON-Schema dicts + plain shaped dicts**.
  Pydantic is used only for config (`MaveDBApiConfig`, `MirrorConfig`, `ServerSettings`) and
  tool *input* args (`Annotated[..., Field(...)]` in `mcp/tools/_common.py`:
  `ResponseMode`, `UrnStr`, `ScoreSetUrnStr`, `SymbolStr`, `SearchText`, `StringList`).
- **Output schemas** are deliberately permissive (`additionalProperties:true`, nothing
  `required`) because `response_mode` projects fields out and the *error envelope must validate
  against the same schema*. Built by an `_envelope(**properties)` helper + a shared `_PAGE`
  block (`mavedb_link/mcp/schemas.py`):

```python
def _envelope(**properties):
    props = {"success": {"type": "boolean"}, "_meta": _META,
             "error_code": {"type": "string"}, "message": {"type": "string"},
             "retryable": {"type": "boolean"}, "recovery_action": {"type": "string"},
             "field": {"type": "string"}, "allowed_values": {"type": "array"},
             "hint": {"type": "string"}, "candidates": {"type": "array"}, **properties}
    return {"type": "object", "additionalProperties": True, "properties": props}

_PAGE = {"total": _INT_NULL, "returned": _INT, "limit": _INT, "offset": _INT,
         "truncated": _BOOL, "next_offset": _INT_NULL}
```

- **The real "model" is the shaping layer** (`services/shaping.py`): pure functions over
  upstream camelCase dicts → snake_case, tiered by `response_mode`. Representative
  (`shape_score_set`):

```python
def shape_score_set(raw, response_mode):
    if response_mode == "minimal":
        return _drop_empty({"urn": raw.get("urn"), "title": raw.get("title")})
    full = response_mode == "full"; rich = response_mode in ("standard", "full")
    payload = {"urn": raw.get("urn"), "title": raw.get("title"),
        "short_description": raw.get("shortDescription"),
        "num_variants": raw.get("numVariants"), "license": _license_short(raw),
        "targets": [_shape_target(t, full=rich) for t in raw.get("targetGenes") or []],
        "experiment_urn": (raw.get("experiment") or {}).get("urn") or raw.get("experimentUrn"),
        "publications": _shape_publications(raw, detail=response_mode),
        "score_calibrations": shape_calibrations(raw.get("scoreCalibrations"), full=full),
        "record_url": _web_url("score-sets", raw.get("urn"))}
    return payload if rich else _drop_empty(payload)
```

- **SQL mirror schema** (`mavedb_link/data/schema.sql`, `SCHEMA_VERSION = 1`):
  `meta` (1-row provenance), `experiment_set`/`experiment`/`score_set` (URN PK + denormalized
  columns + verbatim `record_json`), `score_set_data` (CSVs stored verbatim),
  `gene_index` (case-insensitive gene→set), `mapped_variant` (cross-dataset identity index on
  vrs_id/clingen/variant_urn), `score_distribution` (precomputed histogram+quantiles), and
  `score_set_fts` (**FTS5** virtual table, `unicode61` tokenizer). **MetaDome equivalent**: a
  `transcript` table, a `position_score` table (one row per protein position: tolerance score,
  gnomAD count, ClinVar count), a `domain` table (Pfam), a `meta_domain` mapping table, plus an
  FTS index over gene/transcript.

### A.4 Upstream integration — the HTTP client (copy this)

One external API: **MaveDB REST**, base `https://api.mavedb.org/api/v1`, **no auth**, **httpx
async**. Headers `User-Agent: mavedb-link/{version}`, `Accept: application/json`,
`follow_redirects=True`. Timeout 30 s, `max_concurrency=5` (semaphore), `max_retries=4`.
The full client is `/home/bernt-popp/development/mavedb-link/mavedb_link/api/client.py`. Core:

```python
class MaveDBClient:
    def __init__(self, config=None):
        ...
        self._client: httpx.AsyncClient | None = None
        self._connect_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max(1, config.max_concurrency))
        self._cache = _TTLCache(maxsize=config.cache_size, ttl=float(config.cache_ttl))

    async def _ensure_client(self):
        if self._client is None:
            async with self._connect_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=self._config.request_timeout,
                        headers={"User-Agent": self._config.user_agent, "Accept": "application/json"},
                        follow_redirects=True)
        return self._client

    @staticmethod
    def _raise_for_status(response):
        status = response.status_code
        if status < 400: return
        detail = _extract_detail(response)
        if status == 404: raise NotFoundError(detail or "MaveDB record not found.")
        if status in (400, 422): raise InvalidInputError(detail or "MaveDB rejected the request as invalid.")
        if status == 429: raise RateLimitError(detail or "MaveDB rate limit hit.")
        raise ServiceUnavailableError(f"MaveDB API error (HTTP {status}). {detail}".strip())

    async def _send(self, method, url, *, params=None, json=None, accept=None):
        client = await self._ensure_client()
        headers = {"Accept": accept} if accept else None
        delay = _BACKOFF_BASE_SECONDS                # 0.5 s base, 8.0 s cap
        last_exc = None
        for attempt in range(self._config.max_retries + 1):
            response = None
            async with self._semaphore:              # concurrency bound
                try:
                    response = await client.request(method, url, params=params, json=json, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_exc = exc
            if response is not None and response.status_code not in _RETRYABLE_STATUS:  # {429,500,502,503,504}
                return response
            if attempt >= self._config.max_retries:
                if response is not None: return response
                raise ServiceUnavailableError(f"MaveDB API unreachable after {attempt+1} attempts: {last_exc}") from last_exc
            await asyncio.sleep(random.uniform(0, min(delay, _BACKOFF_MAX_SECONDS)))   # FULL JITTER
            delay = min(delay * 2, _BACKOFF_MAX_SECONDS)

    async def get_json(self, path, *, params=None):
        key = _cache_key("GET", path, params)
        if (cached := self._cache.get(key)) is not None: return cached
        response = await self._send("GET", f"{self._base_url}{path}", params=params)
        self._raise_for_status(response); data = response.json()
        self._cache.set(key, data); return data
    # also get_text (CSV, cached), post_json (NOT cached), get_version, clear_cache, aclose
```

### A.5 Caching

Two layers, **no `requests-cache`, no `vcr` in production**:

1. **In-process TTL+LRU** (`_TTLCache` in `api/client.py`): `OrderedDict[str,(expires,value)]`,
   monotonic-clock TTL, LRU eviction. Defaults `cache_ttl=600 s`, `cache_size=512`. Key =
   `_cache_key(prefix, path, sorted-params)`. **Only idempotent GETs are cached; POST never.**
   The cache is exploited deliberately: the by-hgvs variant scan, distribution, and full scores
   share an identical `start=0, limit=200_000` key per score set, so a warmed score table is
   reused O(1) across three tools.

```python
class _TTLCache:
    def __init__(self, *, maxsize, ttl):
        self._maxsize, self._ttl = maxsize, ttl
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
    def get(self, key):
        if self._maxsize <= 0 or self._ttl <= 0: return None
        hit = self._store.get(key)
        if hit is None: return None
        expires_at, value = hit
        if time.monotonic() >= expires_at: self._store.pop(key, None); return None
        self._store.move_to_end(key); return value
    def set(self, key, value):
        if self._maxsize <= 0 or self._ttl <= 0: return
        self._store[key] = (time.monotonic() + self._ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._maxsize: self._store.popitem(last=False)
```

2. **Optional read-only SQLite mirror** (a pre-downloaded/bundled dataset).
   `MirrorRepository` (`data/repository.py`) opens `mavedb.sqlite` read-only
   (`file:...?mode=ro`), validates `schema_version`, answers upstream-shaped reads, and returns
   `None` on miss (never raises). `HybridClient` (`data/hybrid.py`) **subclasses `MaveDBClient`**
   and serves from the mirror, falling through to live on any miss — the whole service stack
   consumes it unchanged. `data/provenance.py` (a `contextvar`) tags each `_meta.data_source` as
   `mirror|live|mixed` + `mirror_as_of`.

```python
class HybridClient(MaveDBClient):
    async def get_json(self, path, *, params=None):
        hit = self._mirror_json(path, params)
        if hit is not _MISS:
            provenance.record("mirror", mirror_as_of=self._mirror_as_of); return hit
        provenance.record("live"); return await super().get_json(path, params=params)
```

**Ingest/bundling**: `ingest/builder.py::build_database(dump_path, db_path)` streams a MaveDB
Zenodo bulk-dump zip into a fresh SQLite DB and atomically `os.replace()`-swaps it (stores
camelCase records verbatim, precomputes distributions, builds gene/mapped-variant indexes +
FTS). `ingest/parsing.py` has the pure helpers (`denamespace_csv`, `compute_distribution`,
`parse_annotations`).

> ⚠️ **Important caveat for MetaDome**: the mirror is *designed-but-not-yet-wired*.
> `MirrorConfig` declares Zenodo/GitHub-release acquisition fields but **no downloader code
> exists** (grep found zero fetch code). `build_database` only runs from an already-present
> dump; docker `entrypoint.sh` says *"mavedb-link has no local data to build (the API is the
> live source)"*. The operational path today is **live API + in-memory TTL cache**. If MetaDome
> exposes a per-gene/per-transcript bulk dataset, this mirror design is the right target — but
> you must also write the downloader the sibling skipped.

### A.6 Identifier resolution

**Fully local, regex-based — no `hgnc-link` dependency.** `mavedb_link/identifiers.py` is pure
functions over the `urn:mavedb:` scheme: `classify_urn`, `is_*_urn`, `looks_like_gene_symbol`
(`^[A-Z][A-Z0-9-]{0,19}$`), `variant_index_of` (parses `#<n>` for numeric join/sort),
`validate_score_set_urn` (raises `InvalidInputError` with a hint). **Gene-symbol → records
resolution is delegated upstream**: `get_gene_score_sets()` hits MaveDB's own `/genes/{symbol}`
(MaveDB does the HGNC resolution) and unions with the target facet. So: identifier *parsing*
local; gene *identity* delegated to upstream.

> For MetaDome: gene symbol / transcript ID resolution can be delegated to MetaDome's own
> dashboard endpoints (it has a gene/transcript picker). Parse transcript IDs and protein
> positions locally.

### A.7 Response envelope & token budgeting (copy this)

- **`response_mode` has 4 tiers**: `minimal | compact | standard | full` (default `compact`).
  minimal = identity anchors only (and drops `next_commands`/`capabilities_version` from
  `_meta`); compact = high-signal, empties dropped; standard = structured minus heavy free text;
  full = everything.
- **Pagination** is uniform offset-based `{total, returned, limit, offset, truncated,
  next_offset}`; `get_variant_scores` also mirrors `start`/`next_start`.
- **Token budgeting**: `RESPONSE_TOKEN_BUDGET = 25_000`, estimate = `chars/4`. Domain data is
  never silently trimmed — over-budget responses set `_meta.truncated/budget_exceeded/steer` and
  prepend a leaner re-call to `next_commands`.

The envelope builder (`mavedb_link/mcp/envelope.py::run_mcp_tool`) — **the single most reusable
piece**; it never raises, always returns a structured dict:

```python
async def run_mcp_tool(tool_name, call, *, context=None):
    ctx = context or McpErrorContext(tool_name=tool_name)
    provenance.begin(); start = time.perf_counter()
    try:
        result = await call()
        elapsed = int((time.perf_counter() - start) * 1000)
        if isinstance(result, dict):
            success = bool(result.setdefault("success", True))
            meta = {**(result.get("_meta") or {}), "tool": tool_name, "request_id": _request_id(),
                    "elapsed_ms": elapsed, "truncated": bool(result.get("truncated")),
                    **provenance.snapshot()}                  # data_source / mirror_as_of
            _stamp_capabilities_version(meta)
            result["_meta"] = _shape_meta(meta, ctx.response_mode)
            result["_meta"]["token_estimate"] = _estimate_tokens(result)
            _apply_budget_guard(result, ctx)                  # flag + steer over-budget
            metrics.record(tool_name, elapsed, ok=success)
        return result
    except Exception as exc:                                  # error boundary: RETURN, never raise
        envelope = _error_envelope(exc, ctx)                  # {success:False, error_code, message,
                                                              #  retryable, recovery_action, candidates?}
        metrics.record(tool_name, elapsed, ok=False)
        return envelope
```

`_meta` always carries `tool, request_id, elapsed_ms, truncated, data_source, mirror_as_of`,
plus `token_estimate`; compact/standard/full add `next_commands` + `capabilities_version`.
**Capabilities versioning** (`mcp/capabilities.py`): `capabilities_version()` is a cached
16-char SHA256 of the discovery contract (excluding volatile `build`), echoed in every `_meta`
so warm clients skip re-fetch; `TOOLS` is a frozen list a test asserts equals the registered set.
**`next_commands`** (`mcp/next_commands.py`): `cmd(tool, **args)` → `{tool, arguments}`; per-tool
`after_*` chainers steer the canonical workflow with `widen_cmd`/`page_offset_cmd`.

### A.8 Error handling

Typed exceptions (`mavedb_link/exceptions.py`, base `MaveDBError(message, status_code)`):
`InvalidInputError(field, allowed, hint)`, `NotFoundError(suggestions)`,
`AmbiguousQueryError(candidates)`, `DataUnavailableError`, `RateLimitError`,
`ServiceUnavailableError`. The data plane **raises**; the MCP plane **returns** a dict.
`envelope._classify()` maps to **7 stable codes** (`constants.ERROR_CODES`):
`invalid_input, not_found, ambiguous_query, data_unavailable, rate_limited,
upstream_unavailable, internal_error`. Each error envelope adds `retryable`, `recovery_action`
(`retry_backoff|reformulate_input|switch_tool|lower_response_mode`), optional
`field/allowed_values/hint/candidates`, and steering `next_commands`. `ArgValidationMiddleware`
(`mcp/middleware.py`) catches arg-binding failures *before* the tool body → did-you-mean +
valid-param-list envelope, and normalizes arg aliases (`query`→`text`).

### A.9 Tests — how they mock the upstream

`pytest` + `pytest-asyncio` (`asyncio_mode="auto"`) + **`respx`** (httpx mock). **No vcr, no
cassettes** — fixtures are **hand-authored Python dicts** of real-shaped camelCase payloads
(`tests/fixtures.py`: `SCORE_SET_RAW`, `GENE_RESPONSE`, `MAPPED_VARIANTS_RAW`, `SCORES_CSV`…
modeled on UBE2I `urn:mavedb:00000001-a-1`). The full stack runs for real; only HTTP is mocked.
`tests/conftest.py` builds layered fixtures with caching disabled and a real
`client`/`service`/`facade` via `set_mavedb_service(service)` injection:

```python
@pytest.fixture
def api_config(): return MaveDBApiConfig(base_url=fixtures.BASE_URL, cache_ttl=0, cache_size=0, max_retries=2)

@pytest.fixture
async def client(api_config):
    c = MaveDBClient(api_config); yield c; await c.aclose()   # httpx calls intercepted by respx

@pytest.fixture
async def facade(service):
    set_mavedb_service(service); mcp = create_mavedb_mcp(); yield mcp; set_mavedb_service(None)

@pytest.fixture
def respx_router():
    with respx.mock(base_url=fixtures.BASE_URL, assert_all_called=False) as router: yield router
```

`test_client.py` asserts status→exception mapping, 429 retry-then-raise (`call_count==3` at
`max_retries=2`), 429-then-success, and cache hit (`route.call_count==1` on a repeat GET).
`test_tools_e2e.py` registers the whole route surface and calls `facade.call_tool(name, args)`,
asserting `structured_content` envelope fields.

### A.10 Config & deps

`config.py`: `MaveDBApiConfig` / `MirrorConfig` / `ServerSettings(BaseSettings)`, env prefix
`MAVEDB_LINK_`, nested delimiter `__`, `.env` support, module-level singleton `settings`.
`pyproject.toml` deps: `httpx>=0.28`, `pydantic>=2.11`, `pydantic-settings>=2.6`,
`fastmcp>=3.2`, `mcp[cli]>=1.27`, `fastapi`, `uvicorn[standard]`, `structlog`, `orjson`, `rich`,
`typer` (dev: `pytest`, `pytest-asyncio`, `pytest-cov/mock/xdist`, **`respx`**, `ruff`, `mypy`).
**No `requests`, no `requests-cache`, no `vcr`.** Entry points:
`mavedb-link = "server:main"` (REST+MCP) and `mavedb-link-mcp = "mcp_server:main"` (stdio).
ruff line-length 100, mypy `strict=True`, coverage `fail_under=80`, plus a LOC budget.

---

## Part B — `spliceailookup-link` (the methodology sibling)

### B.1 File tree & what's unique

```
spliceailookup_link/
  config.py  exceptions.py  variant.py  cli.py  logging_config.py  server_manager.py
  api/      base_client.py  scoring_client.py  ensembl_client.py    # async httpx + error taxonomy
  services/ splice_service.py  telemetry.py                          # alru_cache per-leaf + telemetry
  mcp/      facade.py  errors.py  shaping.py  schema_relax.py  next_commands.py
            provenance.py  resources.py  build_check.py  annotations.py
            tools/  spliceai.py pangolin.py combined.py batch.py resolve.py metadata.py
                    _predict.py _predict_shape.py _common.py _diagnose.py
                    _batch_runner.py _batch_dedup.py
.investigation/   API-REVERSE-ENGINEERING.md  discover.py  capture.py  capture_all.py
                  api_calls.json  bodies.json  controls.json  probes/*.json   # << REVERSE-ENG ARTIFACTS
.claude/skills/   ci-failure-triage/  mcp-tool-change/
```

**What's unique / the methodology gold (lift for MetaDome):**
- `.investigation/` — the entire reverse-engineering trail (browser capture scripts +
  direct-curl probes + the distilled contract doc). **This is the template for MetaDome.**
- `mcp/build_check.py` — per-genome-build chromosome length tables for local build-mismatch
  detection (genomics-specific).
- `mcp/tools/_batch_runner.py` + `_batch_dedup.py` — resilient server-side fan-out with per-item
  retry + dedup.
- `mcp/tools/_common.py::run_with_deadline` — foreground soft-deadline / background-task bridge
  for slow upstreams.
- FastMCP **Tasks** (`fastmcp[tasks]`, `DOCKET_URL`, per-tool `task=True`) — the actual async
  "submit + poll" escape hatch (protocol-owned, not app-owned).

### B.2 Reverse-engineering methodology (FOLLOW THIS FOR METADOME)

A three-phase Playwright + curl workflow, verified against the upstream's open-source repo. The
distilled contract is `.investigation/API-REVERSE-ENGINEERING.md` — captured 2026-06-11, source
of truth confirmed against `github.com/broadinstitute/SpliceAI-lookup` server code.

1. **Phase 1 — UI/network discovery** (`discover.py`): headless Chromium, hook
   `page.on("request")`/`page.on("response")` to log every call, `goto(wait_until="networkidle")`,
   screenshot, then `page.evaluate(...)` to dump **all form controls**
   (inputs/buttons/selects/textareas/labels) and `document.body.innerText` — reveals the input
   field id, submit button, and option params **without reading minified JS**. Outputs
   `controls.json`, `initial_network.json`, `page_text.txt`, screenshots.
2. **Phase 2 — submit + capture bodies** (`capture.py`/`capture_all.py`): drive the form with 3+
   representative inputs covering input variety, filter responses to the data host(s), store
   `resp.text()` bodies, and **wait generously for slow compute**
   (`wait_for_load_state("networkidle", timeout=90000)` + `wait_for_timeout(4000)` — they
   anticipated the slow upstream from the start). Outputs `api_calls.json`, `bodies.json`.
3. **Phase 3 — direct curl probes** (`probes/`): once the endpoint + query shape is known,
   bypass the browser and curl the endpoint directly, varying **one param at a time** (distance,
   gene set, mask analogs) plus deliberate bad inputs — this is how the **error model** (status
   codes vs in-body error strings) and the **timing table** (incl. the 503 ceiling) were
   established. Outputs `dist500.json`, `comp50.json`, `garbage.json`, `invalid.json`, etc.
4. **Verify against source of truth**: MetaDome is open source
   (`github.com/cmbi/metadome`) — confirm endpoint semantics, param defaults, and the
   **async/job model** against the server code; treat it as the tiebreaker.
5. **Write the contract doc** (`API-REVERSE-ENGINEERING.md` template): backend host map with
   in-scope/delegate/defer decisions, a param table (req?/type/default/dashboard-value/meaning),
   full success-response key list, the error model, and **measured timing + rate limits** — then
   drive `config.py` defaults (timeout, concurrency cap, TTL, soft deadline) directly from those
   measurements, and paste trimmed real responses into `tests/fixtures/` as the cassettes.

> **CRITICAL MetaDome difference to verify in Phase 2/3**: MetaDome's tolerance computation is
> very likely a genuine **submit-job-then-poll** async API (a build/analysis endpoint that
> returns a job id, then a status-poll endpoint, then a results fetch) — *unlike* SpliceAI's
> slow-synchronous single GET. If so, MetaDome's client needs a **real poll loop**
> (submit → poll status with backoff until done → fetch result), which neither sibling
> implements directly. The surrounding scaffolding (concurrency cap, retry/backoff,
> `run_with_deadline`, background-task opt-in, error taxonomy, caching, shaping) all transfers;
> only the client's "one slow GET" becomes "submit + poll".

### B.3 Upstream integration

Endpoints (`config.py`), all **GET + JSON over httpx async**:
SpliceAI `https://spliceai-{37,38}-...a.run.app/spliceai/`, Pangolin
`.../pangolin/`, Ensembl VEP `https://rest.ensembl.org` (GRCh38) /
`https://grch37.rest.ensembl.org` (GRCh37). Timeouts `REQUEST_TIMEOUT=90 s`,
`MAX_CONCURRENCY=2` (low — upstream is interactive-only), `QUEUE_WAIT_TIMEOUT=30 s`,
`MAX_RETRIES=3`.

The base client (`spliceailookup_link/api/base_client.py`) mirrors mavedb's design but adds a
queue-wait deadline and a **fault taxonomy**: `SpliceApiError` base, with `DataNotFoundError`,
`UpstreamInputError`, `RateLimitedError`. The defining quirk:

```python
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_INPUT_ERROR_STATUS = frozenset({400, 404, 410, 422})       # deterministic, never retried
```

The scoring client (`scoring_client.py`) handles the upstream's quirk that **failures arrive as
HTTP 200 with an `error` string** — success is verified by *body inspection*, not status:

```python
_PARSE_ERROR_SIGNALS = ("unable to parse", "could not parse", "invalid variant")
_NO_SCORE_SIGNALS = ("did not return any scores", "no scores", "does not overlap")

class ScoringClient(BaseHTTPClient):
    async def score(self, *, model, build, variant, distance, mask, gene_set="basic", ...):
        params = {"hg": hg_for_build(build), "distance": distance, "mask": mask,
                  "bc": gene_set, "variant": variant}
        payload = await self.get_json(self._url(model, build), params)
        error = payload.get("error") if isinstance(payload, dict) else None
        if error:
            lowered = str(error).lower()
            if any(s in lowered for s in _PARSE_ERROR_SIGNALS): raise UpstreamInputError(str(error))
            if any(s in lowered for s in _NO_SCORE_SIGNALS): raise DataNotFoundError(str(error))
            raise DataNotFoundError(str(error))   # unknown error -> not_found (don't hammer)
        return payload
```

> **MetaDome lesson**: web-tool backends frequently report failures with a 200 status + an
> error body (or an empty/sentinel payload). Inspect bodies; map error substrings to typed
> exceptions; treat unknown errors as `not_found` (non-retryable) so you don't hammer a slow
> upstream.

### B.4 Async / long-running job handling (THE most valuable section)

SpliceAI has **no submit-poll** — it's one slow-but-synchronous GET (13–40 s). Slowness is
handled with **five composed mechanisms** (all directly reusable; for MetaDome you additionally
add a real poll loop inside the client, but keep all five wrappers):

**(a) Retry + full-jitter exponential backoff** — `base_client.get_json` (verbatim). Note the
semaphore is acquired **per attempt** and released in `finally` *before* the backoff sleep, so a
backing-off request does not hold a concurrency slot; queue-wait is bounded:

```python
async def get_json(self, url, params):
    client = await self._ensure_client()
    loop = asyncio.get_running_loop()
    queue_deadline = loop.time() + settings.QUEUE_WAIT_TIMEOUT
    delay = _BACKOFF_BASE_SECONDS
    last_exc = None
    for attempt in range(settings.MAX_RETRIES + 1):
        await self._acquire_slot(timeout=max(0.0, queue_deadline - loop.time()))   # bounded queue wait
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            last_exc = exc; status = exc.response.status_code
            if status in _INPUT_ERROR_STATUS:
                raise UpstreamInputError(_extract_error_message(exc.response, status)) from exc
            if status == 429 and attempt == settings.MAX_RETRIES:
                raise RateLimitedError(f"Rate limited by upstream (HTTP 429): {url}") from exc
            if not _is_retryable(exc) or attempt == settings.MAX_RETRIES:
                raise SpliceApiError(f"Upstream HTTP {status} for {url}") from exc
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt == settings.MAX_RETRIES:
                raise SpliceApiError(f"Upstream request failed: {exc!s}") from exc
        finally:
            self._semaphore.release()                  # release BEFORE the backoff sleep
        await asyncio.sleep(random.uniform(0, min(delay, _BACKOFF_MAX_SECONDS)))    # FULL JITTER
        delay = min(delay * 2, _BACKOFF_MAX_SECONDS)
    raise SpliceApiError(f"Retry loop exhausted for {url}: {last_exc!s}")
```

`_acquire_slot` raises `RateLimitedError` if the local cap can't be acquired within
`QUEUE_WAIT_TIMEOUT` (so a saturated server fails fast instead of piling up).

**(b) Foreground soft deadline + background-task bypass** —
`_common.py::run_with_deadline` (verbatim). This bridges a slow blocking call to the client's
MCP timeout: a foreground call gets a `PREDICT_SOFT_DEADLINE_SECONDS=55 s` wall and returns a
retryable error *before the client gives up*; background tasks bypass it. **This is exactly the
wrapper a MetaDome poll loop should sit inside.**

```python
def running_as_task(ctx):
    return bool(ctx is not None and getattr(ctx, "is_background_task", False))

async def run_with_deadline(coro, *, ctx, enforce=True):
    deadline = settings.PREDICT_SOFT_DEADLINE_SECONDS
    bypass = not enforce or running_as_task(ctx)
    if deadline and not bypass:
        try:
            return await asyncio.wait_for(coro, timeout=deadline)
        except TimeoutError as exc:
            raise SpliceApiError(
                f"Scoring exceeded the server's {deadline}s deadline "
                "(comprehensive gene_set and/or a large max_distance are slow).") from exc
    return await coro
```

**(c) MCP background tasks** — the actual "async job" escape hatch. Slow tools opt in with
`task=True` in `@mcp.tool(...)`; the client augments `tools/call` with a `task` field → gets a
`taskId` → polls `tasks/get` → retrieves via `tasks/result`. Backed by FastMCP's 2025-11-25
Tasks protocol (Docket backend, `DOCKET_URL="memory://"`, `fastmcp[tasks]` extra). The protocol
(not the app) owns the client-side polling. **For MetaDome, this is the right pattern for the
slow tolerance-landscape build tool.**

**(d) Cold-start warmup + warmth telemetry** — `SpliceService.warmup()` fires a known-good
sentinel to wake the Cloud Run container before a burst; every response carries
`_meta.served_warm`.

**(e) Per-item batch retry** — `_batch_runner.py::_run_item` (verbatim). One retry per item
inside a batch; terminal vs retryable separation; one bad item never fails its siblings:

```python
_RETRYABLE_CODES = {"rate_limited", "upstream_unavailable"}

async def _run_item(predict_fn, service, *, variant, genome_build, params, retry_backoff_s):
    retried = False; request_id = uuid.uuid4().hex[:12]
    while True:
        try:
            one = await predict_fn(service, variant=variant, genome_build=genome_build, **params)
            return _success_item(one, variant, request_id), "ok", retried
        except Exception as exc:
            item, code = _error_item(exc, variant, genome_build, request_id)
            if code in _RETRYABLE_CODES and not retried:
                retried = True
                if retry_backoff_s: await asyncio.sleep(random.uniform(0, retry_backoff_s))
                continue
            kind = "retryable" if code in _RETRYABLE_CODES else "terminal"
            return item, kind, retried
```

`run_batch` walks items **sequentially** (at `MAX_CONCURRENCY=2`, each item's calls already
saturate the cap), reports `ctx.report_progress`, and returns `terminal_failed` vs a top-level
`retry_variants` list. Two cheap **pre-flight fast-fails** also avoid the slow path: a REF-base
check (`preflight_ref_mismatch`) and a transcript-overlap check (`preflight_no_overlap`), both
conservative (any inconclusive result falls through to real scoring).

### B.5 Tool catalog (7 tools)

`metadata.py::get_server_capabilities` + `warmup`; `resolve.py::resolve_variant`;
`spliceai.py::predict_spliceai`; `pangolin.py::predict_pangolin`;
`combined.py::predict_splicing` (both models + agreement verdict — the default answer);
`batch.py::predict_splicing_batch` (1–25 variants, server-side fan-out). All
`READ_ONLY_OPEN_WORLD`; the four `predict_*` tools carry `task=True`. Common scoring params:
`variant_id, genome_build="GRCh38", max_distance(1–10000)=500, mask="raw", gene_set="basic",
transcripts="mane", response_mode="compact", cross_build_check=True, correlation_id`.
Helper modules (no tools): `_predict.py` (`predict_one` core — `prepare_variant` → progress →
`asyncio.gather(spliceai, pangolin, return_exceptions=True)` under `run_with_deadline` →
diagnose-on-double-failure → shape → agreement), `_predict_shape.py`, `_diagnose.py`.

### B.6 Data model — the variant parser (lift the pattern)

No Pydantic for variants/scores — variants are a **frozen dataclass + precedence-ordered
parser** (`spliceailookup_link/variant.py`), scores are dicts shaped by pure functions. The full
parser (verbatim core), which MetaDome should adapt to *gene symbol / transcript ID / protein
position*:

```python
InputKind = Literal["coordinate", "hgvs", "rsid"]

@dataclass(frozen=True)
class VariantInput:
    kind: InputKind
    value: str   # coordinate -> canonical CHROM-POS-REF-ALT; hgvs/rsid -> cleaned string for VEP

def parse_variant_input(text: str) -> VariantInput:
    if text is None or not str(text).strip():
        raise VariantParseError("Empty variant input. Provide CHROM-POS-REF-ALT, HGVS, or an rsID.")
    t = str(text).strip()
    if looks_like_rsid(t):                                   # ^rs\d+$
        return VariantInput(kind="rsid", value=t.lower())
    tokens = _coordinate_tokens(t)                           # split on [\s:\-]+, validate pos>=1, ACGTN
    if tokens is not None:
        chrom, pos, ref, alt = tokens
        if chrom in _VALID_CHROMS:
            return VariantInput(kind="coordinate", value=f"{chrom}-{pos}-{ref}-{alt}")
        raise UnsupportedContigError(...)                    # well-formed but non-standard contig
    if looks_like_hgvs(t):                                   # [:.]\s*[cgnmr]\. or NM_/ENST prefix
        return VariantInput(kind="hgvs", value=clean_hgvs(t))
    raise VariantParseError("Could not interpret the input as a variant. Supported forms: ...")
```

Note `clean_hgvs` strips website annotations (`(GENE)`, ` (p.Xxx)`) — the same input-normalization
the site does. Score shaping (`mcp/shaping.py`) is mode-gated: heavy fields (`ref_alt_scores`,
`exon_model`, `allNonZeroScores`) appear **only in `full`**; `_apply_max_transcripts` caps lists
and emits `transcripts_truncated:{kept,total}`; `_collapse_identical_transcripts` merges
byte-identical blocks. **MetaDome's per-position tolerance track is a large array — apply the
same mode-gating + truncation metadata.**

### B.7 Caching

**In-process only** (`async_lru.alru_cache`), no on-disk/requests-cache. `CACHE_SIZE=1024`,
`CACHE_TTL_MINUTES=1440` (24 h — safe because scores are deterministic per param tuple). Wrapped
per-leaf in `SpliceService.__init__`:

```python
self._score_cached   = alru_cache(maxsize=cache_size, ttl=ttl_seconds)(self._score_uncached)
self._resolve_cached = alru_cache(maxsize=cache_size, ttl=ttl_seconds)(self._resolve_uncached)
```

Cache key for scoring = `(model, build, variant_id, distance, mask, gene_set, raw, consequence)`.
**Batch dedup** (`_batch_dedup.py::build_dedup_plan`) is a second layer: resolve every input to
its canonical id, the first index per canonical is the **owner** (does the real call), duplicates
are served by `copy.deepcopy` of the owner's result with `_meta.cache="deduped"`. So a variant
submitted in two notations is scored once.

### B.8 Identifier resolution

Resolved **locally + via Ensembl VEP** — no `ensembl-link`/`hgnc-link` dependency.
`parse_variant_input` classifies; coordinates normalize locally; HGVS/rsID go to
`EnsemblVepClient.resolve_hgvs` → reads back `vcf_string` (the CHROM-POS-REF-ALT the scoring API
needs) + `most_severe_consequence`. Multi-allelic rsIDs set `ambiguous:True` +
`variant_ids:[...]` → `AmbiguousVariantError`. Genome build is an explicit param baked into both
hosts; **build mismatch is detected locally first** (`build_check.py` per-build length tables).

### B.9 Response envelope, errors, tests

- **`response_mode`**: `minimal` (headline + one number), `compact` (default), `standard`,
  `full` (+ heavy arrays). `_meta` stamped uniformly by `errors.py::run_mcp_tool._stamp`:
  always `request_id`, `timing.elapsed_ms`, `unsafe_for_clinical_use:True`; non-lean adds
  `capabilities_version` (content hash). `next_commands` + `see_also` (cross-server hints to
  gnomad-link/genereviews-link/gtex-link/uniprot-link) on every response; both toggle via
  `include_hints`/`include_see_also`. `schema_relax.py::relax_output_schema` strips `required`
  so error envelopes pass output-schema validation.
- **Error codes** (`errors.py::_classify`, order-sensitive): `build_mismatch`, `ref_mismatch`,
  `ambiguous`, `invalid_input`, `not_found`, `unsupported_contig`, `rate_limited`,
  `validation_failed`, `upstream_unavailable`, `internal_error`. Each envelope carries
  `retryable`, `recovery_action`, `fallback_tool`/`fallback_args`, prose `recovery`. **Delivery
  is fleet-uniform**: on failure `run_mcp_tool` *raises* `fastmcp.exceptions.ToolError` whose
  message is the compact-JSON envelope (passed through unredacted despite
  `mask_error_details=True`) — *except* batch per-item errors, which stay in-band.
- **Tests** — dual strategy: **`respx`** for HTTP clients (recorded fixtures in
  `tests/fixtures/api_responses.py` — trimmed real responses pasted as Python dicts;
  *these are the cassettes*) + a **`StubService`** for the MCP/tool layer (records calls,
  returns fixtures, injectable faults). Helpers: `structured(result)`,
  `expect_tool_error(mcp, name, args)` (calls a failing tool and `json.loads` the `ToolError`
  message back to a dict). Stack: `pytest-asyncio` (`asyncio_mode="auto"`), `respx`,
  `pytest-cov` (fail_under 80).

### B.10 Config & deps

`Settings(BaseSettings)` env prefix `SPLICEAILOOKUP_LINK_`. Async stack adds over mavedb:
`async-lru` (caching), **`fastmcp[tasks]>=3.2.0`** (the `[tasks]` extra enables Docket background
tasks), `asgi-correlation-id`. Entry point `spliceailookup-link = "spliceailookup_link.cli:app"`.

---

## Part C — Patterns `metadome-link` should reuse

### C.1 Copy nearly verbatim (rename domain only)
- **Async httpx client** — `mavedb-link/api/client.py::MaveDBClient` + `_TTLCache` +
  `_cache_key`/`_extract_detail`. Dependency-light, semaphore-bounded, full-jitter backoff,
  status→typed-exception mapping, TTL+LRU GET memoization. Highest-value single file.
- **Error taxonomy + queue-wait** — `spliceailookup-link/api/base_client.py::BaseHTTPClient`
  (`SpliceApiError`/`DataNotFoundError`/`UpstreamInputError`/`RateLimitedError`,
  `_acquire_slot` queue-wait). Merge with the mavedb client.
- **MCP envelope boundary** — `mavedb-link/mcp/envelope.py::run_mcp_tool` +
  `McpErrorContext` + `_classify` + `_error_envelope` + `build_arg_error_envelope` +
  `_apply_budget_guard` (and/or `spliceailookup-link/mcp/errors.py` for the raise-ToolError
  variant). Decide *return-dict* (mavedb) vs *raise-ToolError* (splice) early — both are
  fleet-valid; mavedb's return-dict is simpler.
- **Typed exceptions** — `mavedb-link/exceptions.py` (6 classes with
  `field/allowed/hint/suggestions/candidates`). Rename base only.
- **Capabilities + content-hash version** — `mavedb-link/mcp/capabilities.py`
  (`build_capabilities`, cached `capabilities_version`, frozen `TOOLS` list).
- **next_commands** — `mavedb-link/mcp/next_commands.py` (`cmd`, `widen_cmd`,
  `page_offset_cmd`); only the `after_*` chainers are domain-specific.
- **Arg-validation middleware** — `mavedb-link/mcp/middleware.py::ArgValidationMiddleware`
  (did-you-mean + alias normalization). Reusable as-is.
- **Permissive output-schema helpers** — `mavedb-link/mcp/schemas.py::_envelope`/`_PAGE` +
  `spliceailookup-link/mcp/schema_relax.py::relax_output_schema`.
- **Response-mode shaping discipline** — `mavedb-link/services/shaping.py` (`_drop_empty`,
  4-tier projection) + `spliceailookup-link/mcp/shaping.py` (mode-gated heavy fields,
  `_apply_max_transcripts` truncation metadata, identical-record collapse).
- **Config layout** — `mavedb-link/config.py` (`ApiConfig`/`MirrorConfig`/`ServerSettings`
  pydantic-settings with `ENV_PREFIX__nested`).
- **Diagnostics metrics** — `mavedb-link/mcp/metrics.py` (rolling-window latency percentiles).
- **Test harness** — both repos' `tests/conftest.py` + fixtures: respx for clients + a
  stub/injected service for tools + hand-authored payload dicts as cassettes. Copy wholesale.

### C.2 Lift for the slow/async upstream (MetaDome's defining challenge)
- `spliceailookup-link/mcp/tools/_common.py::run_with_deadline` + `running_as_task` — the
  foreground-deadline / background-bypass bridge. **Wrap MetaDome's poll loop in this.**
- FastMCP **Tasks** wiring — `fastmcp[tasks]`, `DOCKET_URL`, per-tool `task=True` on the slow
  tolerance-landscape tool. The real "submit + poll" escape hatch.
- `_batch_runner.py::run_batch`/`_run_item` + `_batch_dedup.py::build_dedup_plan` — if MetaDome
  exposes a multi-transcript / multi-gene batch tool.
- HTTP-200-with-error body inspection (`scoring_client.py`) — likely needed for the MetaDome
  dashboard backend.

### C.3 Adapt (do not copy blindly)
- **Identifier parsing** (`spliceailookup-link/variant.py`) — replace the variant regexes with
  MetaDome's domain: gene symbol → transcript ID → protein position. Delegate gene/transcript
  *identity* to MetaDome's own picker endpoints (as mavedb delegates to `/genes/{symbol}`);
  parse positions/IDs locally. Do **not** take a hard dependency on hgnc-link.
- **SQLite mirror** (`mavedb-link/data/` + `ingest/`) — adopt **only if** MetaDome exposes a
  bulk per-gene/per-transcript download (tolerance scores are static per build, so this could
  cut the slow upstream out of the hot path entirely). Schema → `transcript`, `position_score`
  (tolerance + gnomAD count + ClinVar count per position), `domain` (Pfam), `meta_domain`
  mapping, FTS over gene/transcript. **Note: mavedb left the downloader unwritten — you'd have
  to write the acquisition code.** Until then, default to **live API + in-memory TTL cache**.
- **Tool catalog** — map mavedb's shape onto MetaDome:
  `get_server_capabilities`/`get_diagnostics` (copy) · `search`/`resolve_gene` ·
  `get_tolerance_landscape(transcript, response_mode)` (≈ `get_variant_scores`, the big array —
  paginate + mode-gate + maybe `task=True`) · `get_position(transcript, position)`
  (≈ `get_variant_score`) · `get_domains(transcript)` (Pfam) ·
  `get_meta_domain(transcript, position)` (homologue mapping) ·
  `get_variant_counts(transcript[, position])` (gnomAD/ClinVar).
- **Build awareness** — reuse `spliceailookup-link/mcp/build_check.py` only if MetaDome tools
  are genome-coordinate-aware; MetaDome is primarily *protein-position*-centric, so build logic
  may be minimal.

### C.4 Decisions to make before coding
1. **Is MetaDome's upstream submit-poll or slow-synchronous?** (Phase 2/3 of the
   reverse-engineering must answer this. Drives whether you write a poll loop.)
2. **Return-dict envelope (mavedb) vs raise-ToolError (splice)?** Pick one for the whole server.
3. **Live-only + TTL cache, or build the SQLite mirror?** Start live-only; add the mirror only if
   a bulk dump exists and latency demands it.
4. **Response-mode field map** for the per-position tolerance array (the token-budget hot spot).

---

### Source files quoted (all absolute paths)
- `/home/bernt-popp/development/mavedb-link/mavedb_link/api/client.py`
- `/home/bernt-popp/development/mavedb-link/mavedb_link/mcp/envelope.py`
- `/home/bernt-popp/development/mavedb-link/mavedb_link/mcp/schemas.py`
- `/home/bernt-popp/development/mavedb-link/mavedb_link/services/shaping.py`
- `/home/bernt-popp/development/mavedb-link/mavedb_link/data/repository.py`, `data/hybrid.py`, `data/schema.sql`
- `/home/bernt-popp/development/mavedb-link/mavedb_link/exceptions.py`, `identifiers.py`, `config.py`
- `/home/bernt-popp/development/mavedb-link/tests/conftest.py`, `tests/fixtures.py`
- `/home/bernt-popp/development/spliceailookup-link/.investigation/API-REVERSE-ENGINEERING.md`
- `/home/bernt-popp/development/spliceailookup-link/spliceailookup_link/api/base_client.py`, `scoring_client.py`, `ensembl_client.py`
- `/home/bernt-popp/development/spliceailookup-link/spliceailookup_link/mcp/tools/_common.py`, `_batch_runner.py`, `_batch_dedup.py`
- `/home/bernt-popp/development/spliceailookup-link/spliceailookup_link/variant.py`, `mcp/shaping.py`, `mcp/errors.py`
- `/home/bernt-popp/development/spliceailookup-link/tests/conftest.py`, `tests/fixtures/api_responses.py`
