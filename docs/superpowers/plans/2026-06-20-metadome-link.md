# metadome-link Implementation Plan

> Historical record — this document records the implementation plan as of its date. Current
> behavior is defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `metadome-link`, a read-only FastMCP server wrapping the MetaDome web API (per-protein-position missense tolerance landscapes, Pfam domains, meta-domain homolog variant aggregation, gnomAD/ClinVar per-position counts), federated in the GeneFoundry `-link` fleet.

**Architecture:** Fleet "two-plane" design. **Data plane** (`api/`, `cache/`, `services/`) calls MetaDome via async httpx, normalizes to plain dicts, raises typed exceptions, caches completed landscapes on disk. **MCP plane** (`mcp/`) is lifted from `mondo-link` — `run_mcp_tool` owns the `{success,_meta}` envelope and returns (never raises) typed errors. MetaDome computes landscapes asynchronously (Celery, cold builds up to ~1h), so the async model is an explicit `request_tolerance_landscape` → poll `get_tolerance_landscape` split with `status:"processing"` as a first-class success state.

**Tech Stack:** Python ≥3.12, `uv`+hatchling, FastMCP 3.x, `mcp[cli]`, httpx (async), pydantic / pydantic-settings, structlog, FastAPI+uvicorn (unified transport), SQLite (stdlib) result cache, pytest + pytest-asyncio + respx, ruff + mypy(strict).

## Global Constraints

- `requires-python = ">=3.12"`; build backend **hatchling**; license **MIT**; **commit `uv.lock`**; no `.python-version` file.
- Runtime dep floor: `fastapi>=0.115,<1`, `uvicorn[standard]>=0.46,<1`, `pydantic>=2.11,<3`, `pydantic-settings>=2.6,<3`, `httpx>=0.28,<1`, `structlog>=24.4,<27`, `orjson>=3.10,<4`, `rich>=13,<16`, `typer>=0.12,<1`, `mcp[cli]>=1.27,<2`, `fastmcp>=3.2,<4`, `async-lru>=2.0,<3`.
- Dev deps: `pytest>=8.3,<10`, `pytest-asyncio>=0.24,<2`, `pytest-cov>=5,<8`, `pytest-mock>=3.14,<4`, `pytest-xdist>=3.6,<4`, `respx>=0.21,<1`, `ruff>=0.8,<1`, `mypy>=1.13,<3`, `pre-commit>=4,<5`.
- ruff: line-length 100, target py312, `extend-select=["E","W","F","I","N","UP","B","C4","S","T20","SIM","RUF"]`, `ignore=["E501","B008","S101","N812"]`, double quotes; mypy `strict=true`, python 3.12; pytest `asyncio_mode="auto"`, function loop scope; coverage `fail_under=80`, `htmlcov`.
- Env prefix `METADOME_LINK_`, nested delimiter `__`. Package name `metadome_link`. Resource family `metadome://`. Namespace for router = `metadome`.
- 7-code error taxonomy EXACTLY: `invalid_input`, `not_found`, `ambiguous_query`, `data_unavailable`, `rate_limited`, `upstream_unavailable`, `internal_error`.
- `response_mode` ∈ `{minimal,compact,standard,full}`, default `compact`. Every `compact`+ response carries `_meta.next_commands`. Every record-derived payload carries `recommended_citation`. Every `_meta` carries `data_versions`.
- All FastMCP instances: `mask_error_details=True`. All tools: `READ_ONLY_OPEN_WORLD` annotations, `output_schema=`, description first sentence = discovery summary ending `Signature: tool(args...)`.
- Tool names `verb_noun`, ≤50 chars, `[a-z0-9_]`.
- `MetaDome` base URL: `https://stuart.radboudumc.nl/metadome/api`. `metadome_data_version = "gencode19-gnomad2.0.2-clinvar20180603-pfam30-app1.0.1"`. Verbatim citation: "MetaDome: Pathogenicity analysis of genetic variants through aggregation of homologous human protein domains. Wiel L, Baakman C, Gilissen D, Veltman JA, Vriend G, Gilissen C. Human Mutation. 2019;40(8):1030-1038. doi:10.1002/humu.23798".
- Reference repos to lift fleet boilerplate from (read them; copy + rename `mondo`→`metadome`): `/home/bernt-popp/development/mondo-link` (MCP plane, strict mypy, output_schema), `/home/bernt-popp/development/clinvar-link` (CI, Docker, pre-commit), `/home/bernt-popp/development/mavedb-link` (async httpx client + TTL cache). Reverse-engineering capture fixtures live at `/tmp/metadome-captures/`.

---

## File Structure

```
metadome-link/
├── pyproject.toml  uv.lock  README.md  CHANGELOG.md  LICENSE  AGENTS.md  CLAUDE.md  Makefile
├── .env.example  .env.docker.example  .pre-commit-config.yaml  .dockerignore  (.gitignore exists)
├── mcp_server.py  server.py
├── docker/{Dockerfile, entrypoint.sh, docker-compose.yml, docker-compose.npm.yml, README.md}
├── .github/workflows/{ci.yml, docker.yml, security.yml}
├── scripts/check_file_size.py
├── docs/{architecture.md, deployment.md, usage.md}   (research/ + superpowers/ already exist)
├── metadome_link/
│   ├── __init__.py  config.py  constants.py  identifiers.py  exceptions.py
│   ├── logging_config.py  buildinfo.py  server_manager.py  app.py
│   ├── api/{__init__.py, client.py, models.py}
│   ├── cache/{__init__.py, store.py}
│   ├── services/{__init__.py, metadome_service.py, resolution.py, landscape.py,
│   │             pagination.py, shaping.py, citation.py}
│   └── mcp/
│       ├── __init__.py  facade.py  envelope.py  capabilities.py  resources.py
│       ├── annotations.py  next_commands.py  schemas.py  middleware.py  metrics.py  arg_help.py
│       ├── service_adapters.py
│       └── tools/{__init__.py, _common.py, discovery.py, transcripts.py, landscape.py,
│                  positions.py, domains.py, analysis.py}
└── tests/{conftest.py, fixtures/, test_*.py, unit/test_output_schemas.py}
```

---

## Task 1: Project scaffold, config, constants, exceptions, identifiers, tooling

**Files:**
- Create: `pyproject.toml`, `Makefile`, `LICENSE`, `AGENTS.md`, `CLAUDE.md`, `.pre-commit-config.yaml`, `.env.example`, `metadome_link/__init__.py`, `metadome_link/config.py`, `metadome_link/constants.py`, `metadome_link/exceptions.py`, `metadome_link/identifiers.py`, `metadome_link/logging_config.py`, `metadome_link/buildinfo.py`, `tests/__init__.py`, `tests/test_identifiers.py`, `tests/test_config.py`
- Reference: `mondo-link/pyproject.toml`, `mondo-link/Makefile`, `mondo-link/{mondo_link/config.py,constants.py,exceptions.py,logging_config.py,buildinfo.py}`, `clinvar-link/.pre-commit-config.yaml`

**Interfaces:**
- Produces:
  - `metadome_link.config.settings` — module singleton `ServerSettings` (pydantic-settings, prefix `METADOME_LINK_`). Fields: `host:str="0.0.0.0"`, `port:int=8000`, `transport:Literal["unified","http","stdio"]="unified"`, `mcp_path:str="/mcp"`, `cors_origins:list[str]=[]`, `log_level:str="INFO"`, `log_format:Literal["json","console"]="console"`, nested `metadome:MetaDomeSettings`, `cache:CacheSettings`.
  - `MetaDomeSettings`: `base_url:str="https://stuart.radboudumc.nl/metadome/api"`, `request_timeout_s:float=30.0`, `poll_soft_deadline_s:float=20.0`, `poll_initial_interval_s:float=2.0`, `poll_max_interval_s:float=8.0`, `politeness_rate_per_s:float=3.0`, `politeness_burst:int=5`, `max_retries:int=3`.
  - `CacheSettings`: `db_path:str="data/metadome_cache.sqlite"`, `ttl_transcripts_s:int=21600`, `lru_results:int=64`, `lru_transcripts:int=256`.
  - `metadome_link.constants` — `SCHEMA_VERSION="1"`, `METADOME_DATA_VERSION="gencode19-gnomad2.0.2-clinvar20180603-pfam30-app1.0.1"`, `DATA_VERSIONS:dict` (`{"assembly":"GRCh37","gencode":"v19","gnomad":"r2.0.2","clinvar":"2018-06-03","pfam":"30.0","metadome_app":"1.0.1"}`), `RECOMMENDED_CITATION:str` (verbatim Wiel 2019, from Global Constraints), `METADOME_LICENSE="MIT (https://github.com/laurensvdwiel/metadome)"`, `RESEARCH_USE_NOTICE="Research use only; not for clinical decision support, diagnosis, treatment, or patient management."`, `DATA_CURRENCY_CAVEAT="MetaDome data are GRCh37/hg19 with gnomAD r2.0.2 and ClinVar 2018-06-03; per-position counts are historical. Use live gnomAD/ClinVar for current data."`, `MAX_BATCH_POSITIONS=50`, `DEFAULT_PAGE_LIMIT=200`, `MAX_PAGE_LIMIT=1000`, `RESPONSE_MODES=["minimal","compact","standard","full"]`, `DEFAULT_RESPONSE_MODE="compact"`, `ENST_RE=re.compile(r"^ENST\d{11}\.\d+$")`.
  - `metadome_link.exceptions` — base `MetaDomeError(Exception)` + subclasses each carrying `error_code` matching the taxonomy: `InvalidInputError`("invalid_input"), `NotFoundError`("not_found"), `AmbiguousQueryError`("ambiguous_query", `.candidates:list`), `DataUnavailableError`("data_unavailable"), `RateLimitedError`("rate_limited"), `UpstreamUnavailableError`("upstream_unavailable"), `InternalError`("internal_error"). Each accepts `(message, *, retryable=False, recovery_action=None, **extra)` and stores `.extra` dict.
  - `metadome_link.identifiers` — `normalize_gene_symbol(s:str)->str` (strip/upper), `is_transcript_id(s:str)->bool` (matches `ENST_RE`), `validate_transcript_id(s:str)->str` (returns normalized or raises `InvalidInputError` with `field="transcript_id"`, `hint="Ensembl transcript id with version, e.g. ENST00000269305.4"`), `looks_like_transcript_query(s:str)->bool` (startswith `ENST`).
  - `metadome_link.logging_config.configure_logging()->structlog.BoundLogger`.
  - `metadome_link.buildinfo.build_info()->dict` (`{"git_sha":..., "built_at":...}`; best-effort, never raises).

- [ ] **Step 1: Lift & adapt scaffold from mondo-link.** Read `mondo-link/pyproject.toml`, `Makefile`, `mondo_link/{config.py,constants.py,exceptions.py,logging_config.py,buildinfo.py}`, `LICENSE`, `clinvar-link/.pre-commit-config.yaml`. Copy them into metadome-link, renaming package `mondo_link`→`metadome_link`, env prefix `MONDO_LINK_`→`METADOME_LINK_`, server name `mondo-link`→`metadome-link`. Set `[project.scripts]` to `metadome-link="server:main"`, `metadome-link-mcp="mcp_server:main"`, `metadome-link-cache="metadome_link.cache.store:main"`. Replace mondo-specific deps with the Global-Constraints dep floor + `async-lru` (drop any `pyyaml`/ingest-only deps). Strip mondo data/ingest settings from `config.py`; add `MetaDomeSettings` and `CacheSettings` nested models and the fields listed in Interfaces.

- [ ] **Step 2: Write `constants.py`, `exceptions.py`, `identifiers.py`** with exactly the symbols in Interfaces. `exceptions.py` example shape:

```python
class MetaDomeError(Exception):
    error_code = "internal_error"
    def __init__(self, message: str, *, retryable: bool = False,
                 recovery_action: str | None = None, **extra: object) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.recovery_action = recovery_action
        self.extra: dict[str, object] = dict(extra)

class InvalidInputError(MetaDomeError):
    error_code = "invalid_input"
class NotFoundError(MetaDomeError):
    error_code = "not_found"
class AmbiguousQueryError(MetaDomeError):
    error_code = "ambiguous_query"
    def __init__(self, message: str, *, candidates: list[object], **kw: object) -> None:
        super().__init__(message, candidates=candidates, **kw)
        self.candidates = candidates
class DataUnavailableError(MetaDomeError):
    error_code = "data_unavailable"
class RateLimitedError(MetaDomeError):
    error_code = "rate_limited"
class UpstreamUnavailableError(MetaDomeError):
    error_code = "upstream_unavailable"
class InternalError(MetaDomeError):
    error_code = "internal_error"
```

- [ ] **Step 3: Write failing tests** `tests/test_identifiers.py` and `tests/test_config.py`:

```python
# tests/test_identifiers.py
import pytest
from metadome_link.identifiers import (
    is_transcript_id, validate_transcript_id, normalize_gene_symbol, looks_like_transcript_query)
from metadome_link.exceptions import InvalidInputError

def test_is_transcript_id_requires_version():
    assert is_transcript_id("ENST00000269305.4")
    assert not is_transcript_id("ENST00000269305")  # no version
    assert not is_transcript_id("TP53")

def test_validate_transcript_id_raises_on_unversioned():
    with pytest.raises(InvalidInputError) as ei:
        validate_transcript_id("ENST00000269305")
    assert ei.value.error_code == "invalid_input"
    assert ei.value.extra.get("field") == "transcript_id"

def test_normalize_gene_symbol():
    assert normalize_gene_symbol(" tp53 ") == "TP53"

def test_looks_like_transcript_query():
    assert looks_like_transcript_query("ENST00000269305.4")
    assert not looks_like_transcript_query("TP53")
```

```python
# tests/test_config.py
from metadome_link.config import settings, ServerSettings

def test_settings_defaults():
    s = ServerSettings()
    assert s.port == 8000
    assert s.metadome.base_url.endswith("/metadome/api")
    assert s.transport in {"unified", "http", "stdio"}

def test_constants_data_versions():
    from metadome_link.constants import DATA_VERSIONS, RECOMMENDED_CITATION
    assert DATA_VERSIONS["assembly"] == "GRCh37"
    assert "humu.23798" in RECOMMENDED_CITATION
```

- [ ] **Step 4: Run `uv sync --group dev` then `uv run pytest tests/test_identifiers.py tests/test_config.py -v`.** Expected: PASS. Then `uv run ruff check metadome_link tests` and `uv run mypy metadome_link` — Expected: clean.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat: scaffold metadome-link package, config, constants, exceptions, identifiers"`

---

## Task 2: MetaDome async HTTP client (`api/`)

**Files:**
- Create: `metadome_link/api/__init__.py`, `metadome_link/api/client.py`, `metadome_link/api/models.py`, `tests/fixtures/__init__.py`, `tests/fixtures/metadome/{get_transcripts_TP53.json,result_TP53.json,metadomain_p175.json}`, `tests/test_api_client.py`
- Reference: `mavedb-link/.../api/client.py` (httpx async + `_TTLCache` + backoff + status→exception mapping). Capture fixtures at `/tmp/metadome-captures/`.

**Interfaces:**
- Consumes: `metadome_link.config.settings`, `metadome_link.exceptions.*`, `metadome_link.identifiers.validate_transcript_id`, `metadome_link.constants.ENST_RE`.
- Produces: `metadome_link.api.client.MetaDomeClient` (async, constructed with optional `settings`/`httpx.AsyncClient` for injection) with methods:
  - `async get_transcripts(gene: str) -> list[dict]` — GET endpoint 1; returns the (normalized) `trancript_ids` list (each: `{"gencode_id","aa_length","has_protein_data","refseq_ids":list[str]}` — splits `refseq_nm_numbers` on `, `). Empty list if unknown gene (does NOT raise).
  - `async submit_visualization(transcript_id: str) -> str` — POST endpoint 2; returns echoed id; 400→`InvalidInputError`.
  - `async get_status(transcript_id: str) -> str` — GET endpoint 3; returns raw status string (`PENDING|SENT|STARTED|RECEIVED|RETRY|SUCCESS|FAILURE`).
  - `async get_result(transcript_id: str) -> dict` — GET endpoint 4; returns normalized landscape dict (coerces every `ClinVar[].clinvar_ID` to str; leaves `positional_annotation` length == aa_length). 404→`NotFoundError`.
  - `async get_error(transcript_id: str) -> dict` — GET endpoint 5.
  - `async get_metadomain_annotation(transcript_id: str, protein_position: int, requested_domains: dict[str, list[int]]) -> dict` — POST endpoint 6; coerces `pathogenic_variants[].clinvar_ID` to str.
  - `async poll_until_ready(transcript_id: str, *, soft_deadline_s: float) -> tuple[str, dict | None]` — submit-aware poll loop: returns `("ready", result_dict)` if SUCCESS within deadline, `("processing", None)` if still building at deadline, `("failed", error_dict)` on FAILURE. Honors politeness limiter + interval backoff (initial→max). NEVER blocks past `soft_deadline_s`.
  - `async aclose() -> None`.
  - Internal: a token-bucket politeness limiter; jittered exponential backoff on 429/5xx/timeouts mapped to `RateLimitedError`/`UpstreamUnavailableError`. Trailing slashes per endpoint. POST `Content-Type: application/json`.
- `metadome_link/api/models.py`: thin TypedDicts/`@dataclass` for `TranscriptSummary`, `LandscapePosition`, `Domain` (optional; client may return plain dicts — but define for typing).

- [ ] **Step 1: Materialize fixtures.** Copy `/tmp/metadome-captures/get_transcripts_TP53.json`→`tests/fixtures/metadome/get_transcripts_TP53.json`, `result_TP53_live.json`→`result_TP53.json` (trim `positional_annotation` to ~20 representative residues incl. p.35 ClinVar and p.175 meta-domain, but keep `aa_length`-consistent length small for the fixture and adjust top-level accordingly — document the trim), `metadomain_p175_populated.json`→`metadomain_p175.json`. If `/tmp` is gone, recreate minimal fixtures from `docs/research/03-metadome-api.md` §3 examples.

- [ ] **Step 2: Write failing tests** `tests/test_api_client.py` using **respx** to mock all 6 endpoints from fixtures. Cover: transcript list parsing (`trancript_ids` typo handled, refseq split), unknown gene → `[]`, submit 400 → `InvalidInputError`, status passthrough, result `clinvar_ID` coerced to str, metadomain coercion, and `poll_until_ready` three outcomes (immediate SUCCESS; PENDING-then-SUCCESS; FAILURE; PENDING-past-deadline → `("processing", None)`).

```python
import json, pathlib, httpx, respx, pytest
from metadome_link.api.client import MetaDomeClient
FX = pathlib.Path(__file__).parent / "fixtures" / "metadome"
BASE = "https://stuart.radboudumc.nl/metadome/api"

def _load(name): return json.loads((FX / name).read_text())

@respx.mock
async def test_get_transcripts_parses_typo_key():
    respx.get(f"{BASE}/get_transcripts/TP53").mock(return_value=httpx.Response(200, json=_load("get_transcripts_TP53.json")))
    c = MetaDomeClient()
    out = await c.get_transcripts("TP53")
    assert any(t["gencode_id"] == "ENST00000269305.4" and t["has_protein_data"] for t in out)
    assert isinstance(out[0]["refseq_ids"], list)
    await c.aclose()

@respx.mock
async def test_unknown_gene_returns_empty():
    respx.get(f"{BASE}/get_transcripts/NOSUCHGENE").mock(return_value=httpx.Response(200, json={"message":"No transcripts...","trancript_ids":[]}))
    c = MetaDomeClient(); assert await c.get_transcripts("NOSUCHGENE") == []; await c.aclose()

@respx.mock
async def test_poll_processing_at_deadline():
    respx.post(f"{BASE}/submit_visualization/").mock(return_value=httpx.Response(200, json={"transcript_id":"ENST00000269305.4"}))
    respx.get(f"{BASE}/status/ENST00000269305.4/").mock(return_value=httpx.Response(200, json={"status":"PENDING"}))
    c = MetaDomeClient()
    state, res = await c.poll_until_ready("ENST00000269305.4", soft_deadline_s=0.05)
    assert state == "processing" and res is None
    await c.aclose()
```

- [ ] **Step 3: Implement `api/client.py`.** Lift the httpx-async + TTL-cache + backoff skeleton from `mavedb-link`'s client; adapt to the 6 MetaDome endpoints, trailing-slash rules, the `trancript_ids` typo, `clinvar_ID`→str coercion, and the `poll_until_ready` loop (submit once, then loop: `get_status`; on terminal return; sleep `min(interval*1.5, max_interval)` with small jitter via index-based variation, respecting politeness limiter; stop when elapsed ≥ `soft_deadline_s`). Map timeouts/`httpx.ConnectError`→`UpstreamUnavailableError(retryable=True)`, 429→`RateLimitedError(retryable=True)`, 5xx→`UpstreamUnavailableError(retryable=True)`.

- [ ] **Step 4: Run `uv run pytest tests/test_api_client.py -v`** → PASS; `uv run mypy metadome_link/api` → clean.

- [ ] **Step 5: Commit.** `feat: add async MetaDome API client with poll loop and fixtures`

---

## Task 3: On-disk result cache + in-memory TTL (`cache/`)

**Files:** Create `metadome_link/cache/__init__.py`, `metadome_link/cache/store.py`, `tests/test_cache.py`

**Interfaces:**
- Consumes: `metadome_link.config.settings`, `metadome_link.constants.METADOME_DATA_VERSION`.
- Produces: `metadome_link.cache.store.ResultCache` with:
  - `__init__(self, db_path: str | None = None, data_version: str | None = None)` — opens/creates SQLite `results(transcript_id TEXT, data_version TEXT, fetched_at TEXT, json TEXT, PRIMARY KEY(transcript_id,data_version))`; creates parent dir.
  - `get_result(transcript_id: str) -> dict | None` (keyed by `(transcript_id, data_version)`; in-mem LRU in front).
  - `put_result(transcript_id: str, landscape: dict) -> None`.
  - `cached_transcript_ids() -> list[str]`; `stats() -> dict` (`{"on_disk":N,"lru_size":M,"data_version":...}`); `clear() -> int`; `close()`.
  - `TTLCache` generic (key→value, TTL seconds) used for transcript lists.
  - Module `main()` (Typer app) for the `metadome-link-cache` script: subcommands `status`, `clear`, `warm GENE...` (resolves+submits popular transcripts — `warm` may be a thin stub calling the service later; `status`/`clear` fully implemented).

- [ ] **Step 1: Write failing tests** `tests/test_cache.py`: put/get round-trips by data_version (a different data_version misses), `cached_transcript_ids`, `stats`, `clear`, TTL expiry (inject a clock or use ttl=0 → immediate miss). Use a `tmp_path` db.

- [ ] **Step 2: Implement `cache/store.py`** (stdlib `sqlite3`, `json`, `functools`/`OrderedDict` LRU; `datetime` for fetched_at — pass timestamps in, don't call `Date.now`-equivalents in a way that breaks determinism; use `datetime.now(UTC)` is fine here in Python). Add the Typer `main()`.

- [ ] **Step 3: Run `uv run pytest tests/test_cache.py -v`** → PASS; mypy clean.

- [ ] **Step 4: Commit.** `feat: add SQLite result cache + in-memory TTL cache`

---

## Task 4: MCP-plane core (lift from mondo-link)

**Files:** Create `metadome_link/mcp/__init__.py`, `mcp/envelope.py`, `mcp/annotations.py`, `mcp/metrics.py`, `mcp/next_commands.py`, `mcp/middleware.py`, `mcp/arg_help.py`, `mcp/service_adapters.py`, `tests/test_envelope.py`
- Reference: the same-named files in `mondo-link/mondo_link/mcp/`.

**Interfaces:**
- Produces (mirroring mondo, renamed):
  - `mcp.envelope.run_mcp_tool(tool_name, call, *, context=None)`, `McpErrorContext(tool_name, arguments=None, response_mode="compact")`, `McpToolError(error_code, message, **extra)`, `classify_exception(exc)->(code,msg)`. Must inject `success`/`_meta`, tier `_meta` by response_mode, map every `MetaDomeError` subclass to its `error_code` (use `getattr(exc,"error_code","internal_error")`, carry `retryable`/`recovery_action`/`extra`), and ALWAYS include `_meta.data_versions = DATA_VERSIONS`.
  - `mcp.annotations.READ_ONLY_OPEN_WORLD`.
  - `mcp.metrics` — `record(tool,elapsed,ok)`, `snapshot()`.
  - `mcp.next_commands` — `cmd(tool, **args)` + `after_*` builders (added per-tool in later tasks).
  - `mcp.middleware.ArgValidationMiddleware` + `build_arg_error_envelope`.
  - `mcp.arg_help.tool_signature(...)`.
  - `mcp.service_adapters.get_metadome_service()/set_metadome_service(svc)` (global DI registry; raises `InternalError` if unset).

- [ ] **Step 1: Copy mondo's `envelope.py, annotations.py, metrics.py, next_commands.py, middleware.py, arg_help.py, service_adapters.py`** into `metadome_link/mcp/`. Rename `mondo`→`metadome`, `get_mondo_service`→`get_metadome_service`. In `envelope.py`: ensure `_error_envelope` reads `error_code`/`retryable`/`recovery_action`/`extra` from `MetaDomeError`; add `data_versions` into `_meta` in both success and error paths (import `DATA_VERSIONS`).

- [ ] **Step 2: Write `tests/test_envelope.py`:** a success dict gets `success:true` + `_meta.tool/request_id/data_versions`; raising `NotFoundError("x", recovery_action="switch_tool")` inside `call` yields `{success:false,error_code:"not_found",retryable:false,recovery_action:"switch_tool"}`; `response_mode="minimal"` strips `next_commands`; `compact` keeps it.

- [ ] **Step 3: Run `uv run pytest tests/test_envelope.py -v`** → PASS; mypy strict clean.

- [ ] **Step 4: Commit.** `feat: add MCP-plane core (envelope, annotations, metrics, middleware) from fleet template`

---

## Task 5: Services — shaping, pagination, citation (pure utilities)

**Files:** Create `metadome_link/services/__init__.py`, `services/shaping.py`, `services/pagination.py`, `services/citation.py`, `tests/test_services_utils.py`
- Reference: `mondo-link/mondo_link/services/{shaping.py,pagination.py,citation.py}`.

**Interfaces:**
- Produces:
  - `services.shaping.shape_record(record, mode)`, `select_fields(payload, fields)`, `RESPONSE_MODES`, `DEFAULT_RESPONSE_MODE`, and a `char_budget_guard(payload, *, max_chars)->payload` that, when over budget, truncates list fields and injects `dropped_summary`.
  - `services.pagination.paginate(items, *, limit, offset)->(page, block)` where `block={total,returned,limit,offset,truncated,next_offset}`.
  - `services.citation.recommended_citation(*, transcript_id=None, gene_name=None)->str` (returns `RECOMMENDED_CITATION` + optional ` Transcript {tid}.`) and `citation_template()->str`.

- [ ] **Step 1: Write failing tests** `tests/test_services_utils.py`: `paginate` math (total/returned/truncated/next_offset for limit<len and limit≥len), `shape_record` drops null/empty in compact and keeps all in full, `recommended_citation` contains the doi.

- [ ] **Step 2: Implement** the three modules (adapt mondo's shaping/pagination; citation uses metadome constants).

- [ ] **Step 3: Run tests** → PASS; mypy clean.

- [ ] **Step 4: Commit.** `feat: add response shaping, pagination, citation utilities`

---

## Task 6: MetaDome service orchestration (`services/metadome_service.py`, `resolution.py`, `landscape.py`)

**Files:** Create `metadome_link/services/metadome_service.py`, `services/resolution.py`, `services/landscape.py`, `tests/test_metadome_service.py`
- Depends on Tasks 2, 3, 5.

**Interfaces:**
- Consumes: `MetaDomeClient`, `ResultCache`/`TTLCache`, shaping/pagination/citation, identifiers, exceptions, constants.
- Produces `metadome_link.services.metadome_service.MetaDomeService(client, cache, *, settings=settings)` with async methods returning **plain dicts** (no envelope), each raising typed exceptions on error. All include `recommended_citation` and rely on the envelope to add `_meta`:
  - `async resolve_transcript(query, *, response_mode) -> dict` — if `looks_like_transcript_query`: `validate_transcript_id` + echo a minimal `{transcript_id, resolved_from:"id"}`; else `get_transcripts(gene)`; empty→`NotFoundError(f"No GRCh37 transcripts for gene '{gene}'")`; sort by `aa_length` desc; mark `canonical` = first `has_protein_data` entry; shape per mode. Adds `next_commands` data for `after_resolve_transcript`.
  - `async request_landscape(transcript_id, *, response_mode) -> dict` — `validate_transcript_id`; `submit_visualization`; one `get_status`; map to `{job_id:tid,transcript_id:tid,status:"ready" if SUCCESS else "processing",poll_after_s,eta_hint,cold_build_warning}`; if status FAILURE → fetch `/error/` summary and raise `UpstreamUnavailableError`.
  - `async get_landscape(transcript_id, *, position_start=None, position_stop=None, limit, offset, response_mode) -> dict` — cache-first: `cache.get_result`; on miss call `client.poll_until_ready(tid, soft_deadline_s=settings.metadome.poll_soft_deadline_s)`: `("ready",res)`→`cache.put_result`+continue; `("processing",None)`→return `{success:True,status:"processing",transcript_id,poll_after_s,_meta hints}`; `("failed",err)`→`UpstreamUnavailableError`. With a result: build top-level (`transcript_id,gene_name,protein_ac,refseq_ids,domains`), slice `positional_annotation` by `[position_start,position_stop]` if given else `paginate(..., limit, offset)`; shape per mode; attach pagination block.
  - `async get_position(transcript_id, position, *, response_mode) -> dict`, `async get_variant_counts(transcript_id, *, position=None, position_start=None, position_stop=None, source="both", response_mode) -> dict`, `async compare_positions(transcript_id, positions, *, response_mode) -> dict`, `async get_domains(transcript_id, *, response_mode) -> dict`, `async get_meta_domain(transcript_id, position, *, domains=None, limit, offset, response_mode) -> dict`, `async summarize_intolerant_regions(transcript_id, *, threshold=0.5, min_run=3, top_n=15, response_mode) -> dict`.
  - A private `async _require_landscape(transcript_id) -> dict` used by the position/variant/compare/domains/metadomain/summarize methods: returns the cached landscape, else does ONE `poll_until_ready` with the soft deadline; if not ready raises `NotFoundError(f"Tolerance landscape for {tid} is not built yet", recovery_action="switch_tool")` carrying `next_commands` hints to request+poll.
  - `services.resolution` helpers (sort/canonical pick, query-type detection). `services.landscape` pure helpers: `slice_positions`, `position_to_entry(landscape,pos)` (1-based index with bounds → `InvalidInputError` if out of range), `intolerant_runs(landscape,threshold,min_run,top_n)`, `domains_for_position(landscape,pos)` (derive `{PF:[consensus_pos]}` for metadomain), `variant_counts_for(entry, source)`.

- [ ] **Step 1: Write failing tests** `tests/test_metadome_service.py` with an injected fake/respx client + temp cache. Cover: resolve (gene→canonical flagged, ENST passthrough, unknown→NotFound), request (ready vs processing), get_landscape (processing path returns status, ready path caches + paginates + slices), `_require_landscape` not-ready→NotFound, get_position out-of-range→InvalidInput, summarize finds the intolerant run in the fixture, get_meta_domain derives domains from landscape, get_variant_counts source filter.

- [ ] **Step 2: Implement** the service + helpers.

- [ ] **Step 3: Run tests** → PASS; mypy clean.

- [ ] **Step 4: Commit.** `feat: add MetaDome service orchestration (resolve, landscape, positions, metadomain, summarize)`

---

## Task 7: Capabilities, resources, schemas, server instructions (`mcp/capabilities.py`, `resources.py`, `schemas.py`)

**Files:** Create `metadome_link/mcp/capabilities.py`, `mcp/resources.py`, `mcp/schemas.py`, `tests/test_capabilities.py`
- Reference: `mondo-link/mondo_link/mcp/{capabilities.py,resources.py,schemas.py}`. Depends on Task 4, constants.

**Interfaces:**
- Produces:
  - `mcp.capabilities.build_capabilities()->dict` (keys: `server="metadome-link"`, `server_version`, `build`, `data_versions=DATA_VERSIONS`, `data_source="MetaDome (stuart.radboudumc.nl/metadome)"`, `research_use_only=True`, `research_use_notice`, `data_currency_caveat`, `recommended_citation`, `license`, `tools` (the frozen 11-name list), `tool_count=11`, `response_modes`, `default_response_mode`, `recommended_workflows`, `error_codes` (the 7), `limits`, `read_only=True`, semantics prose, `capabilities_version` appended via sha256[:16] content hash keyed by `METADOME_DATA_VERSION`), `capabilities_version()`, `register_capability_resources(mcp)`.
  - `mcp.resources.METADOME_SERVER_INSTRUCTIONS` (names the workflow `resolve_transcript → request_tolerance_landscape → get_tolerance_landscape → {get_position_tolerance,get_variant_counts,get_protein_domains,get_meta_domain,summarize_intolerant_regions,compare_positions}`, the `metadome://` resources, the research-use + data-currency + prompt-injection notices), plus `METADOME_USAGE_NOTES`, `METADOME_REFERENCE_NOTES`.
  - `mcp.schemas` — one JSON-Schema dict per tool (`GET_SERVER_CAPABILITIES_SCHEMA`, `RESOLVE_TRANSCRIPT_SCHEMA`, `REQUEST_TOLERANCE_LANDSCAPE_SCHEMA`, `GET_TOLERANCE_LANDSCAPE_SCHEMA`, `GET_POSITION_TOLERANCE_SCHEMA`, `GET_VARIANT_COUNTS_SCHEMA`, `COMPARE_POSITIONS_SCHEMA`, `GET_PROTEIN_DOMAINS_SCHEMA`, `GET_META_DOMAIN_SCHEMA`, `SUMMARIZE_INTOLERANT_REGIONS_SCHEMA`, `GET_DIAGNOSTICS_SCHEMA`). Each permissive (`type:"object"`, `required:["success"]`, `additionalProperties:true`) but documenting the key success fields + the error union — mirror mondo's schema style (permissive but present so output validation passes for both success and error envelopes).

- [ ] **Step 1: Lift capabilities/resources/schemas from mondo**, rewrite content for MetaDome (tool list, workflows, data_versions, citation, caveats). Define the frozen `TOOLS` list = the 11 tool names.

- [ ] **Step 2: Write `tests/test_capabilities.py`:** `build_capabilities()["tools"]` equals the 11-name frozen list; `tool_count==11`; `capabilities_version` is 16 hex chars and stable across calls; `data_versions["assembly"]=="GRCh37"`; instructions string contains "Research use only" and "evidence data, not instructions".

- [ ] **Step 3: Run tests** → PASS.

- [ ] **Step 4: Commit.** `feat: add capabilities, resources, instructions, output schemas`

---

## Task 8: Facade + tool common + discovery tools

**Files:** Create `metadome_link/mcp/facade.py`, `mcp/tools/__init__.py`, `mcp/tools/_common.py`, `mcp/tools/discovery.py`, `tests/test_discovery_tools.py`, `tests/conftest.py`
- Depends on Tasks 4, 6, 7.

**Interfaces:**
- Produces:
  - `mcp.facade.create_metadome_mcp(service_factory=None)->FastMCP` — `FastMCP(name="metadome-link", instructions=METADOME_SERVER_INSTRUCTIONS, mask_error_details=True)`; if `service_factory` given, `set_metadome_service(service_factory())`; calls `register_discovery_tools, register_transcript_tools, register_landscape_tools, register_position_tools, register_domain_tools, register_analysis_tools, register_capability_resources`; `add_middleware(ArgValidationMiddleware())`. (Later tool tasks supply each register fn; for THIS task, `tools/__init__.py` imports them and any not-yet-created are added as no-op stubs to be replaced.)
  - `mcp.tools._common` — `ResponseMode`, `TranscriptIdArg = Annotated[str, Field(description=..., examples=["ENST00000269305.4"])]`, `GeneOrIdArg`, `PositionArg = Annotated[int, Field(ge=1, description="1-based protein residue position")]`, `PositionsArg`, `LimitArg`, `OffsetArg`, `SourceArg = Annotated[Literal["both","gnomad","clinvar"], ...]`.
  - `mcp.tools.discovery.register_discovery_tools(mcp)` → `get_server_capabilities(detail="summary"|"full", response_mode)` and `get_diagnostics()` (build_info + cache.stats() via service + metrics.snapshot() + a cheap upstream reachability flag).
  - `tests/conftest.py` fixtures: `metadome_service` (built on a respx-mocked client + temp cache), `facade = create_metadome_mcp(service_factory=lambda: metadome_service)`, and `call_tool(mcp,name,args)` in-memory `fastmcp.Client` helper (from §13 of conventions).

- [ ] **Step 1: Write `tools/__init__.py`** with `register_all` importing the six `register_*_tools` (stub the five not-yet-written ones as `def register_X_tools(mcp): ...` no-ops in their modules created empty here, OR define them inline as pass-through and replace in later tasks). Write `_common.py`, `facade.py`, `discovery.py`.

- [ ] **Step 2: Write `tests/conftest.py`** (fixture chain + `call_tool`) and `tests/test_discovery_tools.py`: `call_tool(facade,"get_server_capabilities",{})` → `success:true`, `tool_count==11`, `_meta.capabilities_version` present; `get_diagnostics` → cache stats present.

- [ ] **Step 3: Run `uv run pytest tests/test_discovery_tools.py -v`** → PASS.

- [ ] **Step 4: Commit.** `feat: add FastMCP facade, shared tool args, discovery tools`

---

## Tasks 9-13: Tool modules (parallelizable — each its own file + its own register fn)

> Each replaces its stub `register_*_tools` from Task 8. Each tool: `@mcp.tool(name=..., title=..., annotations=READ_ONLY_OPEN_WORLD, output_schema=<schema>, tags=..., description="... Signature: name(args).")`, body wraps `get_metadome_service().<method>(...)` in a `call()` closure, sets `_meta.next_commands` via `after_*`, returns `run_mcp_tool(name, call, context=McpErrorContext(name, arguments=..., response_mode=response_mode))`. Pattern is exactly Task 4.1 of the conventions doc (`mondo` diseases.py). Add the matching `after_*` builders to `mcp/next_commands.py`.

### Task 9: `mcp/tools/transcripts.py` — `resolve_transcript`
- Test `tests/test_tool_transcripts.py`: gene→canonical flagged + `next_commands` → `request_tolerance_landscape`; ENST passthrough; unknown gene → `error_code:"not_found"`. Commit `feat: add resolve_transcript tool`.

### Task 10: `mcp/tools/landscape.py` — `request_tolerance_landscape`, `get_tolerance_landscape`
- Test `tests/test_tool_landscape.py`: request ready vs processing; get processing-state (`success:true,status:"processing"`, `next_commands`→self); get ready returns domains + paginated positions + `data_versions`; slice by position range; FAILURE → `upstream_unavailable`. Commit `feat: add tolerance-landscape request/poll tools`.

### Task 11: `mcp/tools/positions.py` — `get_position_tolerance`, `get_variant_counts`, `compare_positions`
- Test `tests/test_tool_positions.py`: position fields incl `sw_dn_ds`; out-of-range → `invalid_input`; variant_counts source filter + ClinVar id+URL; compare_positions batch table + per-item error for bad position; not-ready landscape → `not_found` + recovery `switch_tool`. Commit `feat: add position, variant-count, compare tools`.

### Task 12: `mcp/tools/domains.py` — `get_protein_domains`, `get_meta_domain`
- Test `tests/test_tool_domains.py`: domains list shape; meta_domain derives `requested_domains` from landscape when omitted; populated p.175 returns `normal_variants`/`pathogenic_variants` with homolog `gene_name`; non-metadomain residue → empty lists (not error); pagination. Commit `feat: add protein-domains and meta-domain tools`.

### Task 13: `mcp/tools/analysis.py` — `summarize_intolerant_regions`
- Test `tests/test_tool_analysis.py`: returns ranked intolerant runs below threshold with domain overlap + counts; respects `top_n`/`min_run`; not-ready → `not_found`. Commit `feat: add summarize_intolerant_regions tool`.

> After 9-13 land, replace the no-op stubs; run the full suite.

---

## Task 14: Server entry points + FastAPI health (`server.py`, `mcp_server.py`, `server_manager.py`, `app.py`)

**Files:** Create `server.py`, `mcp_server.py`, `metadome_link/server_manager.py`, `metadome_link/app.py`, `tests/test_e2e.py`
- Reference: mondo's same files. The service for the running server is built from a real `MetaDomeClient` + `ResultCache` and registered via `set_metadome_service` in the manager startup.

**Interfaces:**
- `server.py:main()` argparse `--transport {unified,http,stdio} --host --port --log-level`. `mcp_server.py:main()` stdio (env-guards first, per conventions §3.2). `server_manager.UnifiedServerManager` with `start_stdio_server()`/unified mount of `mcp.http_app(path=settings.mcp_path)` under FastAPI on :8000. `app.py` FastAPI with `GET /health`→`{"status":"ok","data_versions":...,"capabilities_version":...}`.

- [ ] **Step 1: Lift mondo's `server.py/mcp_server.py/server_manager.py/app.py`**, rename, wire the metadome service construction (client+cache) into manager startup; `aclose()` client + `close()` cache on shutdown.
- [ ] **Step 2: Write `tests/test_e2e.py`:** `httpx.ASGITransport(app)` GET `/health`→200 + data_versions; in-memory `fastmcp.Client` lists EXACTLY the 11 `EXPECTED_TOOLS`; one resolve→request→get(processing) happy path via respx-mocked upstream.
- [ ] **Step 3: Run full suite `uv run pytest -q`** → PASS; mypy strict clean; `uv run ruff check` clean.
- [ ] **Step 4: Commit.** `feat: add unified/stdio server entry points and health endpoint`

---

## Task 15: Output-schema invariant test + resources test

**Files:** Create `tests/unit/__init__.py`, `tests/unit/test_output_schemas.py`, `tests/test_resources.py`

- [ ] **Step 1:** `test_output_schemas.py` — for every tool, call it (success + a forced-error path) in all 4 response modes via `call_tool`, and `jsonschema.validate` each output against the tool's `output_schema`. `test_resources.py` — each `metadome://` resource returns; `build_capabilities()["tools"]` == the registered tool set (introspect the facade).
- [ ] **Step 2: Run** → PASS. Add `jsonschema` to dev deps if not transitively present.
- [ ] **Step 3: Commit.** `test: enforce output-schema validity and resource/tool parity`

---

## Task 16: CI, Docker, pre-commit (lift from clinvar-link)

**Files:** Create `.github/workflows/{ci.yml,docker.yml,security.yml}`, `docker/{Dockerfile,entrypoint.sh,docker-compose.yml,docker-compose.npm.yml,README.md}`, `scripts/check_file_size.py`, `.dockerignore`, `.env.docker.example`

- [ ] **Step 1: Lift clinvar-link's** three workflows + Docker set + pre-commit + check_file_size, rename to metadome-link. `entrypoint.sh` simply `exec`s the unified server (NO bulk ingest; cache warms lazily) — mount `/app/data` for the cache. `docker.yml` builds `metadome-link:ci`. Keep all actions SHA-pinned.
- [ ] **Step 2:** `docker build -f docker/Dockerfile -t metadome-link:ci .` succeeds; `docker compose -f docker/docker-compose.yml config` valid; `uv run pre-commit run --all-files` clean.
- [ ] **Step 3: Commit.** `ci: add CI, Docker, and pre-commit (fleet template)`

---

## Task 17: Docs, README, CHANGELOG, AGENTS/CLAUDE, router registration snippet

**Files:** Create `README.md`, `CHANGELOG.md`, `docs/{architecture.md,deployment.md,usage.md}`; update `AGENTS.md`, `CLAUDE.md`; create `docs/router-registration.md`

- [ ] **Step 1:** README in clinvar's section order (Title → What/why → Features → Quick start → MCP client config → Tools (the 11, with signatures) → Example workflow (TP53 resolve→request→get→position→meta_domain) → Configuration → Docker → Citation & License → **Research use disclaimer + data-currency caveat** → Development). `docs/architecture.md` = two-plane + async model; `docs/deployment.md` = container + router; `docs/usage.md` = workflows + response modes. `docs/router-registration.md` = the exact `servers.yaml` entry (`namespace: metadome`, `entrypoints: [resolve_transcript, get_tolerance_landscape]`) + `GF_METADOME_URL` env + `genefoundry-router validate/doctor/list-tools` commands. AGENTS.md/CLAUDE.md state the two-plane invariants.
- [ ] **Step 2: Commit.** `docs: add README, architecture/deployment/usage docs, router registration`

---

## Task 18: Final integration verification

- [ ] **Step 1:** `make ci-local` (format-check, lint, typecheck, test-fast) → all green; `make test-cov` → coverage ≥80%.
- [ ] **Step 2:** Optional `-m integration` live smoke test against TP53 (resolve→request→get) — confirm real upstream still matches the contract; deselected in normal CI.
- [ ] **Step 3:** Verify the 11-tool set + capabilities parity + `data_versions` present on a sample of tool outputs.
- [ ] **Step 4: Commit** any fixups. `chore: final integration verification`

---

## Self-Review (completed)

- **Spec coverage:** §3 API → Tasks 2,6; §4 architecture/cache → Tasks 1-3,6; §5 all 11 tools → Tasks 8-13; §6 envelope/errors/pagination → Tasks 4,5; §7 response_mode → Task 5; §8 capabilities/resources/citation/disclaimers → Task 7; §9 config/transport/scripts → Tasks 1,3,14; §10 tests → Tasks 2-15; §11 CI/Docker/federation → Tasks 16,17; §12 non-goals respected (no ingest, no live enrichment). All covered.
- **Placeholders:** lift-from-sibling steps name exact source files (real, present) and exact renames — not vague TODOs. Novel code (client, cache, service, tools, tests) shown or precisely specified via interfaces.
- **Type consistency:** method names match across tasks (`get_metadome_service`, `MetaDomeService.*`, `ResultCache.get_result/put_result`, `poll_until_ready` 3-state return, `run_mcp_tool`, the 11 frozen tool names). `clinvar_ID`→str coercion specified once in Task 2 and relied on everywhere.
```
