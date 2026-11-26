# GeneFoundry `-link` Fleet Conventions — Template for `metadome-link`

> Reverse-documented from the canonical reference servers in `/home/bernt-popp/development/`.
> Primary references: **`mondo-link`** (richest MCP plane, strict typing, local-index data model)
> and **`clinvar-link`** (best CI/CD + Docker + bundle distribution). Secondary peek: **`gtex-link`**
> (the live-API data-model variant). Router: **`genefoundry-router`**.
>
> **Date:** 2026-06-20. This is the build template for `metadome-link`.

---

## 0. Executive orientation

The fleet is a set of read-only biomedical MCP servers named `<source>-link`, each:

- A **FastMCP 3.x** server (`fastmcp>=3.2.0,<4.0.0`, `mcp[cli]>=1.27.0`) packaged with **`uv`** + **hatchling**, Python **>=3.12**.
- Federated behind **`genefoundry-router`** purely declaratively: the router is a **client** that proxies each backend's **Streamable-HTTP** `/mcp` endpoint and re-exposes its tools namespaced as `<namespace>_<tool>`. Adding a backend = one YAML entry + one env var. No router code changes.
- Built on a **"two planes" architecture** (stated verbatim in every `AGENTS.md`):
  - **Data plane** (`config.py`, `constants.py`, `ingest/`, `data/`, `services/`): fetches/builds data, returns **plain dicts**, raises **typed exceptions**. Never builds envelopes.
  - **MCP plane** (`mcp/`): domain-agnostic scaffolding. `run_mcp_tool` owns `success`/`_meta` and converts exceptions into **returned** structured errors (never raised to the client).
- Two data-model variants — pick ONE for metadome:
  - **Local SQLite index** (mondo, clinvar): download upstream release → build SQLite → serve offline. No live API at request time.
  - **Live upstream API proxy** (gtex): `httpx.AsyncClient` + token-bucket rate limiter + `async-lru` cache against a remote REST API at request time.

> **metadome decision needed:** MetaDome's tolerance/landscape data is served by a web API (stuart.radboudumc.nl/metadome). If that API is reliable and rate-limit-friendly, follow the **gtex live-API pattern**. If you can snapshot it (per-transcript tolerance landscapes) into SQLite, follow the **mondo/clinvar local-index pattern** (preferred by the fleet — faster, offline, deterministic tests). See §11.

---

## 1. Repository / file layout (annotated)

Canonical layout (mondo-link, the most complete MCP plane). `<pkg>` = `metadome_link`, `<x>` = `metadome`.

```
metadome-link/
├── pyproject.toml                 # hatchling + uv; deps, ruff/mypy/pytest/coverage config
├── uv.lock                        # COMMITTED. consumed with --frozen in CI/Docker
├── README.md                      # see §16 for required section structure
├── CHANGELOG.md                   # Keep a Changelog + SemVer (mondo has one; clinvar uses dynamic version)
├── LICENSE                        # MIT
├── AGENTS.md                      # "two planes" + invariants contract (agents/contributors)
├── CLAUDE.md                      # short pointer for Claude Code
├── Makefile                       # self-documenting; all tasks via `uv run` (§5)
├── .env.docker.example            # docker env-var contract
├── .env.example                   # (clinvar only) local env template
├── .pre-commit-config.yaml        # (clinvar only — ADOPT IT) ruff + mypy + std hooks
├── .dockerignore                  # (clinvar) excludes data/, caches, .env* except .env.docker.example
├── .gitignore
├── mcp_server.py                  # ROOT: stdio entry point (Claude Desktop). main() -> manager.start_stdio_server()
├── server.py                      # ROOT: unified entry point (--transport unified|http|stdio)
├── docker/
│   ├── Dockerfile                 # multi-stage python:3.12-slim, non-root, /opt/venv
│   ├── entrypoint.sh              # build/fetch data index, then exec server (unified, :8000)
│   ├── docker-compose.yml         # local dev stack; published host port; data volume
│   ├── docker-compose.npm.yml     # PROD overlay: nginx-proxy-manager, hardened, expose-only
│   └── README.md
├── .github/workflows/             # (clinvar has these — ADOPT; mondo has NONE)
│   ├── ci.yml                     # single 3.12 "quality" job -> make ci-local + make test-cov
│   ├── docker.yml                 # build-and-validate only (no push)
│   └── security.yml               # CodeQL + dependency-review + weekly cron
├── scripts/
│   ├── check_file_size.py         # per-file LOC budget (lint-loc)
│   └── check_deployed_freshness.py# assert deployed build sha == local HEAD
├── docs/
│   ├── architecture.md
│   ├── deployment.md
│   └── usage.md
├── data/                          # gitignored: built SQLite + download cache (local-index model)
│   └── .build.lock
├── metadome_link/                 # THE PACKAGE
│   ├── __init__.py                # __version__ = "0.1.0"; __all__ = ["__version__"]
│   ├── config.py                  # pydantic-settings; env prefix METADOME_LINK_
│   ├── constants.py               # SCHEMA_VERSION, MAX_BATCH_ITEMS, RECOMMENDED_CITATION, LICENSE, ...
│   ├── identifiers.py             # id/curie parsing & normalization helpers
│   ├── exceptions.py              # typed domain exceptions (the 7-code taxonomy sources)
│   ├── logging_config.py          # structlog setup -> configure_logging()
│   ├── buildinfo.py               # build_info(): git sha + built-at for _meta/capabilities
│   ├── server_manager.py          # UnifiedServerManager: stdio / http / unified startup
│   ├── app.py                     # FastAPI app (/health, REST) — mounted under unified
│   ├── data/
│   │   ├── __init__.py
│   │   └── repository.py          # read-only SQLite repo (local-index model)
│   ├── ingest/                    # local-index model: download + build the SQLite index
│   │   ├── cli.py                 # `metadome-link-data` entry: build/refresh/bootstrap/status
│   │   ├── downloader.py          # conditional GET (etag/last-modified) of upstream release
│   │   ├── builder.py             # build_database(config, ...) -> SQLite
│   │   ├── parser.py / parsing.py # parse upstream format
│   │   ├── schema.py / schema.sql # on-disk schema (+ indexes.sql in clinvar)
│   │   └── lock.py                # cross-process build lock
│   ├── services/
│   │   ├── __init__.py
│   │   ├── <x>_service.py         # orchestrates repo/client -> plain dicts
│   │   ├── resolution.py          # free-text -> stable id resolver
│   │   ├── pagination.py          # {total, returned, limit, offset, truncated, next_offset}
│   │   ├── shaping.py             # response_mode projection (minimal|compact|standard|full)
│   │   ├── refresh.py             # optional in-process conditional refresh scheduler
│   │   └── citation.py            # recommended_citation builders
│   └── mcp/                       # THE MCP PLANE (domain-agnostic scaffolding)
│       ├── __init__.py
│       ├── facade.py              # create_<x>_mcp() -> FastMCP (instructions, middleware, register_*)
│       ├── envelope.py            # run_mcp_tool: success/_meta injection + structured errors
│       ├── capabilities.py        # build_capabilities(), capabilities_version(), <x>:// resources
│       ├── resources.py           # instructions string + static notes (license, usage, citation)
│       ├── annotations.py         # READ_ONLY_OPEN_WORLD ToolAnnotations
│       ├── next_commands.py       # cmd()/after_* builders for _meta.next_commands chaining
│       ├── schemas.py             # output_schema JSON Schemas per tool
│       ├── middleware.py          # ArgValidationMiddleware (friendly arg-binding errors)
│       ├── metrics.py             # in-process latency/req/err counters -> get_diagnostics
│       ├── arg_help.py            # tool_signature() rendering for capabilities/errors
│       ├── service_adapters.py    # get/set_<x>_service() DI registry (mondo style)
│       └── tools/                 # one module per tool group
│           ├── __init__.py        # register_*_tools fan-out
│           ├── _common.py         # shared Annotated arg types (ResponseMode, QueryStr, ...)
│           ├── discovery.py       # get_server_capabilities, get_diagnostics
│           ├── <domain>.py        # the domain tools (diseases.py, variants.py, ...)
│           └── batch.py           # batch variants of single-item tools
├── tests/
│   ├── conftest.py                # built_db -> repo -> service -> facade fixtures
│   ├── fixtures/                  # small REAL upstream slice (.txt/.obo/.tsv) for ingest
│   ├── _fixture_db.py             # (clinvar) build_service + in-memory FastMCP call_tool helper
│   └── test_*.py                  # see §13
```

**Naming variations across the fleet (both are valid):**
- mondo splits `mcp/tools/` into many modules + uses a **global service registry** (`service_adapters.set_mondo_service`). Root bootstrap is `server.py:main` and `mcp_server.py:main`.
- clinvar uses **constructor injection** (`create_clinvar_mcp(service_factory=...)`), a `cli.py` Typer app as the main entry, and fewer tool modules.

---

## 2. Python packaging (`pyproject.toml`)

Build backend: **hatchling**. Python: **>=3.12**. License: **MIT**. **No `.python-version` file** in either repo (pin via `requires-python` + CI/Docker `3.12`).

**Versioning:** mondo uses static `version = "0.1.0"`; clinvar uses `dynamic = ["version"]` reading `clinvar_link/__init__.py` via `[tool.hatch.version]`. Either is acceptable; mondo's static `__version__ = "0.1.0"` in `__init__.py` is the simplest.

### 2.1 Three `[project.scripts]` (the fleet contract)

```toml
[project.scripts]
metadome-link = "server:main"                       # or "metadome_link.cli:app" (clinvar/Typer style)
metadome-link-mcp = "mcp_server:main"               # stdio MCP binary
metadome-link-data = "metadome_link.ingest.cli:main" # data build/refresh CLI (local-index model)
```

### 2.2 Runtime dependency floor (every server)

```toml
dependencies = [
    "fastapi>=0.115.0,<1.0.0",
    "uvicorn[standard]>=0.46.0,<1.0.0",
    "pydantic>=2.11.0,<3.0.0",
    "pydantic-settings>=2.6.0,<3.0.0",
    "httpx>=0.28.0,<1.0.0",
    "structlog>=24.4.0,<27.0.0",
    "orjson>=3.10.0,<4.0.0",
    "rich>=13.0.0,<16.0.0",
    "typer>=0.12.0,<1.0.0",
    "mcp[cli]>=1.27.0,<2.0.0",
    "fastmcp>=3.2.0,<4.0.0",
]
```

**Add per data model:**
- Local-index + bundle distribution (clinvar): `async-lru`, `pyyaml`, `zstandard` (bundle compression), and optionally `gunicorn`, `asgi-correlation-id`, `prometheus-client` (observability).
- Live-API proxy (gtex): `async-lru>=2.3.0,<3.0.0` (LRU+TTL cache); rate limiting is hand-rolled (token bucket in `api/client.py`, no `tenacity`/`backoff` dep).

### 2.3 Dev dependency group

```toml
[dependency-groups]
dev = [
    "pytest>=8.3.0,<10.0.0",
    "pytest-asyncio>=0.24.0,<2.0.0",
    "pytest-cov>=5.0.0,<8.0.0",
    "pytest-mock>=3.14.0,<4.0.0",
    "pytest-xdist>=3.6.0,<4.0.0",
    "respx>=0.21.0,<1.0.0",       # http mock (used in downloader unit tests)
    "ruff>=0.8.0,<1.0.0",
    "mypy>=1.13.0,<3.0.0",
    "pre-commit>=4.0.0,<5.0.0",   # clinvar adds this — ADOPT
    "types-PyYAML>=6.0,<7.0",     # if pyyaml is a runtime dep
]
```

### 2.4 Lint / format / typecheck config

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
extend-select = ["E","W","F","I","N","UP","B","C4","S","T20","SIM","RUF"]
ignore = ["E501","B008","S101","N812"]   # mondo's minimal set; clinvar ignores more

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"

[tool.ruff.lint.per-file-ignores]
"tests/**/*" = ["S101", "S104", "S110", "T20", "B011", "SIM105", "SIM108"]
"mcp_server.py" = ["T20"]

[tool.ruff.lint.pydocstyle]
convention = "google"            # mondo only

[tool.mypy]
python_version = "3.12"
strict = true                    # PREFER mondo's strict baseline (clinvar is lenient)
warn_unused_configs = true
disallow_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
warn_unreachable = true
exclude = [".*site-packages.*", ".*/\\.venv/.*", "htmlcov/.*"]

[[tool.mypy.overrides]]
module = ["structlog.*","mcp.*","fastmcp.*","fastapi.*","pydantic.*",
          "pydantic_settings.*","httpx.*","uvicorn.*","typer.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
minversion = "8.0"
addopts = ["--strict-markers", "--strict-config", "-ra"]
testpaths = ["tests"]
asyncio_mode = "auto"            # async tests need NO @pytest.mark.asyncio
asyncio_default_fixture_loop_scope = "function"
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests that hit live upstream",
    "unit: marks tests as unit tests",
    "mcp: marks tests that test MCP functionality",
]

[tool.coverage.run]
source = ["metadome_link"]
omit = ["tests/*", "*/.venv/*"]
# branch = true   # clinvar enables branch coverage

[tool.coverage.report]
fail_under = 80                  # mondo=80, clinvar=70
show_missing = true
exclude_lines = [
    "pragma: no cover","def __repr__","raise NotImplementedError",
    "if __name__ == .__main__.:","if TYPE_CHECKING:",
    "class .*\\bProtocol\\):","@(abc\\.)?abstractmethod",
]

[tool.coverage.html]
directory = "htmlcov"
```

---

## 3. MCP framework & server bootstrap

Framework: **FastMCP** (`from fastmcp import FastMCP`). Tool annotations come from `mcp.types.ToolAnnotations`.

### 3.1 The facade (`mcp/facade.py`) — assembles the FastMCP instance

```python
# mondo_link/mcp/facade.py
from fastmcp import FastMCP
from mondo_link.mcp.capabilities import register_capability_resources
from mondo_link.mcp.middleware import ArgValidationMiddleware
from mondo_link.mcp.resources import MONDO_SERVER_INSTRUCTIONS
from mondo_link.mcp.tools import (
    register_batch_tools, register_discovery_tools, register_disease_tools,
    register_hierarchy_tools, register_xref_tools,
)

def create_mondo_mcp() -> FastMCP:
    """Build a FastMCP instance with all mondo-link tools, resources, middleware."""
    mcp = FastMCP(
        name="mondo-link",
        instructions=MONDO_SERVER_INSTRUCTIONS,
        mask_error_details=True,          # NON-NEGOTIABLE: never leak internals
    )
    register_discovery_tools(mcp)
    register_disease_tools(mcp)
    register_hierarchy_tools(mcp)
    register_xref_tools(mcp)
    register_batch_tools(mcp)
    register_capability_resources(mcp)    # the <x>:// resource family
    mcp.add_middleware(ArgValidationMiddleware())
    return mcp
```

clinvar's variant takes `service_factory` for DI and also registers `register_workflow_prompts(mcp)` (MCP prompts) and two error handlers (`install_validation_error_handler`, `install_output_validation_error_handler`). Both pass `mask_error_details=True` and a rich `instructions=` string.

### 3.2 stdio entry point (`mcp_server.py` at repo root)

```python
#!/usr/bin/env python3
"""Stdio MCP entry point for Claude Desktop and similar clients."""
from __future__ import annotations
import asyncio, os, sys

def main() -> None:
    # Configure env BEFORE importing anything that may print to stdout (stdio safety).
    os.environ.setdefault("MONDO_LINK_TRANSPORT", "stdio")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ.setdefault("FASTMCP_DISABLE_BANNER", "1")
    os.environ.setdefault("FASTMCP_QUIET", "1")
    os.environ.setdefault("NO_COLOR", "1")
    try:
        from mondo_link.logging_config import configure_logging
        from mondo_link.server_manager import UnifiedServerManager
    except Exception as exc:
        print(f"ERROR: mondo_link import failed: {exc}", file=sys.stderr)
        sys.exit(1)
    logger = configure_logging()
    manager = UnifiedServerManager(logger=logger)
    try:
        asyncio.run(manager.start_stdio_server())
    except KeyboardInterrupt:
        logger.info("MCP stdio server shutdown requested")
    except Exception as exc:
        logger.error("MCP stdio server error", error=str(exc)); sys.exit(1)

if __name__ == "__main__":
    main()
```

### 3.3 unified entry point (`server.py`) + `UnifiedServerManager`

`server.py` is an argparse CLI with `--transport {unified,http,stdio}` (default from settings), `--host`, `--port`, `--log-level`, SIGINT/SIGTERM handlers, and dispatches to `UnifiedServerManager`. The **unified** mode mounts the MCP streamable-HTTP ASGI app under the FastAPI app on ONE port (default 8000), combining lifespans:

```python
# server_manager.py (unified)
mcp = create_mondo_mcp()
mcp_asgi = mcp.http_app(path=settings.mcp_path)          # "/mcp"
# combine FastAPI lifespan + MCP lifespan via AsyncExitStack, then:
fastapi_app.mount("/", mcp_asgi)
uvicorn.Server(uvicorn.Config(app=fastapi_app, host=host, port=port, log_config=None, lifespan="on"))
```

This is why the router can proxy each backend at `https://<name>-link.genefoundry.org/mcp` — every backend serves Streamable-HTTP at `/mcp` in unified mode.

---

## 4. Tool definition pattern

Tools live in `mcp/tools/<group>.py` inside a `register_<group>_tools(mcp)` function. Each is an `async def` decorated with `@mcp.tool(...)`, wrapping its body in a `call()` closure passed to `run_mcp_tool`.

### 4.1 Full annotated tool (mondo style — keyword-arg decorator with `output_schema`)

```python
# mondo_link/mcp/tools/diseases.py
from typing import Annotated, Any
from pydantic import Field
from mondo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from mondo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from mondo_link.mcp.next_commands import after_resolve_disease
from mondo_link.mcp.schemas import RESOLVE_DISEASE_SCHEMA
from mondo_link.mcp.service_adapters import get_mondo_service
from mondo_link.mcp.tools._common import QueryStr, ResponseMode

def register_disease_tools(mcp):
    @mcp.tool(
        name="resolve_disease",
        title="Resolve Disease",
        annotations=READ_ONLY_OPEN_WORLD,          # read-only research server
        output_schema=RESOLVE_DISEASE_SCHEMA,       # JSON Schema; output is validated against it
        tags={"disease", "resolve"},
        description=(                                # FIRST SENTENCE = discovery summary;
            "Resolve a disease label, synonym, MONDO id, or external CURIE ... "
            "Signature: resolve_disease(query, response_mode=)."   # ENDS WITH Signature:
        ),
    )
    async def resolve_disease(
        query: QueryStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_mondo_service().resolve_disease(query, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_resolve_disease(payload)
            return payload
        return await run_mcp_tool(
            "resolve_disease",
            call,
            context=McpErrorContext(
                "resolve_disease", arguments={"query": query}, response_mode=response_mode
            ),
        )
```

clinvar's style is equivalent but puts the description in the **function docstring** instead of the decorator `description=`, omits `output_schema` (no enforced output validation), and uses `service_factory()` instead of a global getter. **Prefer mondo's style** (`output_schema` + tested output validation is a stated invariant).

### 4.2 Shared annotated arg types (`mcp/tools/_common.py`)

```python
from typing import Annotated, Literal
from pydantic import Field

ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(description="Verbosity: minimal|compact|standard|full (default compact)."),
]
QueryStr = Annotated[str, Field(description="...", examples=["Marfan syndrome", "MONDO:0008426"])]
FieldsArg = Annotated[list[str] | None, Field(description="Sparse fieldset ...", examples=[["xrefs.OMIM"]])]
```

### 4.3 `READ_ONLY_OPEN_WORLD` annotations (`mcp/annotations.py`)

```python
from mcp.types import ToolAnnotations
READ_ONLY_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True,
)
```

### 4.4 `response_mode` projection (`services/shaping.py`)

`response_mode` is implemented in the **data/service plane** (shaping), NOT the envelope. Four levels:

```python
RESPONSE_MODES = ["minimal", "compact", "standard", "full"]
DEFAULT_RESPONSE_MODE = "compact"

def shape_record(record, mode):
    if mode == "minimal":               # identity anchors only (e.g. {id, name, _meta})
        return {k: v for k, v in record.items() if k in _MINIMAL_KEEP}
    if mode in ("standard", "full"):    # the complete record (identity projection)
        return dict(record)
    # compact (default): drop null/empty values, collapse nested structures to plain strings
    return {k: v for k, v in record.items()
            if k in _PRESERVE_KEYS or not _is_empty(v)}
```

- **minimal**: identity anchors only (`{id, name}` + `_meta`). Token-cheapest.
- **compact** (DEFAULT): drop null/empty, collapse structured fields to plain strings, search hits = `{id, name, score, snippet}`.
- **standard / full**: the complete record, structured fields expanded, full definitions.

There is also `select_fields(payload, fields)` for sparse field projection (`fields=["xrefs.OMIM"]`), always keeping identity anchors.

---

## 5. `uv` usage + Makefile

- Install: `uv sync --group dev`. Lock: `uv lock`. Upgrade: `uv lock --upgrade`.
- All tasks run via `uv run <tool>`. CI/Docker use `uv sync --frozen`. **Commit `uv.lock`.**

Standard targets (self-documenting `help` via awk; `DOCKER_COMPOSE` autodetect):

```
make install        # uv sync --group dev
make format         # uv run ruff format <pkg> tests
make lint           # uv run ruff check <pkg> tests
make typecheck      # uv run mypy <pkg>
make test           # uv run pytest tests -q -m "not integration"
make test-fast      # ... -n auto  (pytest-xdist)
make test-cov       # --cov=<pkg> --cov-report=term-missing/html/xml
make ci-local       # format-check lint-ci [lint-loc] typecheck test-fast
make data           # uv run metadome-link-data build      (local-index model)
make data-refresh   # uv run metadome-link-data refresh    (cron entry point)
make dev            # serve --transport unified --host 127.0.0.1 --port 8000 --dev
make run-prod       # serve --transport unified --host 0.0.0.0 --port 8000
make docker-build/up/down/logs
```

clinvar adds `dmypy`-based `typecheck-fast`; mondo adds `lint-loc` (`scripts/check_file_size.py`) and `verify-deploy`.

---

## 6. Standard response ENVELOPE (`mcp/envelope.py`, clinvar: `mcp/errors.py`)

The envelope is the **MCP-plane boundary**. Services return plain dicts; `run_mcp_tool` injects `success`/`_meta` on success and converts any exception into a **returned** (never raised) structured error.

### 6.1 Success envelope shape

```json
{
  "<domain fields ...>": "...",
  "recommended_citation": "...",        // paste-verbatim citation (see §9)
  "success": true,
  "_meta": {
    "tool": "resolve_disease",
    "request_id": "a1b2c3d4e5f6",       // uuid4 hex[:12]
    "elapsed_ms": 12,                    // standard/full only (tiered, see below)
    "capabilities_version": "9f8e...",   // content hash echo (compact+; omitted in minimal)
    "next_commands": [ {"tool": "...", "arguments": {...}} ]   // compact+; omitted in minimal
  }
}
```

### 6.2 `_meta` tiering by `response_mode` (`_shape_meta`)

| response_mode | `_meta` contents |
|---|---|
| `minimal`  | `{tool, request_id}` only (explicit opt-out of guidance) |
| `compact` (default) | `+ next_commands + capabilities_version` (drops `elapsed_ms` from hot path) |
| `standard` / `full` | full `_meta` including `elapsed_ms` |

**Invariant:** every `compact`-or-richer response carries `_meta.next_commands` (ready-to-call follow-ups); `minimal` is the documented opt-out.

### 6.3 Error envelope shape & taxonomy

The **7-code error taxonomy** (frozen across the fleet, sourced from typed exceptions in `<pkg>/exceptions.py`):

`invalid_input` · `not_found` · `ambiguous_query` · `data_unavailable` · `rate_limited` · `upstream_unavailable` · `internal_error`

```json
{
  "success": false,
  "error_code": "ambiguous_query",
  "message": "client-safe message (<=280 chars)",
  "retryable": false,                   // true for rate_limited/upstream_unavailable/data_unavailable
  "recovery_action": "reformulate_input", // retry_backoff | reformulate_input | switch_tool
  "candidates": [ ... ],                // ambiguous_query / not_found-with-suggestions
  "field": "query", "allowed_values": [...], "hint": "...",  // invalid_input extras
  "_meta": { "tool": "...", "request_id": "...", "next_commands": [...] }
}
```

### 6.4 The envelope core (verbatim, mondo)

```python
async def run_mcp_tool(tool_name, call, *, context=None):
    ctx = context or McpErrorContext(tool_name=tool_name)
    start = time.perf_counter()
    try:
        result = await call()
        elapsed = int((time.perf_counter() - start) * 1000)
        if isinstance(result, dict):
            existing_meta = result.get("_meta") or {}
            success = bool(result.setdefault("success", True))
            meta = {**existing_meta, "tool": tool_name,
                    "request_id": _request_id(), "elapsed_ms": elapsed}
            _stamp_capabilities_version(meta)
            result["_meta"] = _shape_meta(meta, ctx.response_mode)
            metrics.record(tool_name, elapsed, ok=success)
        return result
    except Exception as exc:                    # broad catch = error-boundary contract
        elapsed = int((time.perf_counter() - start) * 1000)
        envelope = _error_envelope(exc, ctx)    # _classify -> code+message, recovery, next_commands
        envelope["_meta"]["elapsed_ms"] = elapsed
        _stamp_capabilities_version(envelope["_meta"])
        envelope["_meta"] = _shape_meta(envelope["_meta"], ctx.response_mode)
        metrics.record(tool_name, elapsed, ok=False)
        logger.warning("mcp_tool_error tool=%s code=%s exc=%s",
                       tool_name, envelope["error_code"], exc.__class__.__name__)
        return envelope
```

`_classify(exc)` maps typed exceptions → `(error_code, client_safe_message)`. `McpToolError(error_code=, message=)` can be raised inside a body for an explicit code. `classify_exception` is the public per-item classifier for batch tools.

### 6.5 Pagination block (list tools)

List tools return: `{total, returned, limit, offset, truncated, next_offset}`. When `truncated`, `next_commands` carries a **forward-page step** (`offset` advanced, no rows re-sent) plus a **widen step** (raise `limit`). Never infer completeness from list length.

---

## 7. Capabilities tool + `capabilities_version` hashing

Two discovery tools: `get_server_capabilities(detail="summary"|"full")` and `get_diagnostics()`.

### 7.1 `capabilities_version` is a content hash of the discovery CONTRACT

```python
# mcp/capabilities.py
_HASH_EXCLUDE = frozenset({"build", "capabilities_version"})  # exclude volatile keys
_VERSION_CACHE: dict[str, str] = {}

def _hash_contract(payload):
    contract = {k: v for k, v in payload.items() if k not in _HASH_EXCLUDE}
    blob = json.dumps(contract, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]   # 16-hex short hash

def capabilities_version() -> str:
    key = _data_version() or "unbuilt"        # keyed by loaded upstream release
    cached = _VERSION_CACHE.get(key)
    if cached is None:
        cached = build_capabilities()["capabilities_version"]
        _VERSION_CACHE[key] = cached
    return cached
```

- The hash **excludes** the per-deploy `build` (git sha/timestamp) and the self-hash, so unrelated redeploys don't churn it. A **warm client** caches the last value seen (echoed in every `_meta.capabilities_version`) and skips re-fetching `get_server_capabilities` while unchanged.

### 7.2 `build_capabilities()` payload (the discovery surface)

Required keys: `server`, `server_version`, `build`, `<data>_version`, `data_source`, `research_use_only: True`, `research_use_notice`, `recommended_citation`, `license`, `tools` (frozen list — must equal the registered tool set), `tool_count`, `response_modes`, `default_response_mode`, `recommended_workflows`, `error_codes` (the 7), `limits` (max/default page sizes, `max_batch_items`), `read_only: True`, plus semantics prose (`truncation_contract`, `response_mode_semantics`, `per_call_meta_semantics`, `capabilities_version_semantics`, `provenance_policy`). `capabilities_version` is appended last via `_hash_contract`.

`get_server_capabilities(detail="summary")` returns a key subset + tool signatures + a `more` pointer; `detail="full"` adds policy notes. `get_diagnostics()` reports index build status, loaded release, counts, schema version, and `metrics.snapshot()` (req/err counts, p50/p95/p99 latency).

---

## 8. Resources pattern (`<x>://...`)

Resources are registered inside `register_capability_resources(mcp)` with `@mcp.resource(uri, mime_type=...)`:

```python
@mcp.resource("mondo://capabilities", mime_type="application/json")
def capabilities() -> str: return json.dumps(build_capabilities(), indent=2)

@mcp.resource("mondo://tools", mime_type="application/json")
async def tools_overview() -> str: return json.dumps(await build_tools_overview(mcp), indent=2)

@mcp.resource("mondo://usage", mime_type="text/plain")
def usage() -> str: return MONDO_USAGE_NOTES

@mcp.resource("mondo://reference", mime_type="text/plain")  # also: research-use, citation
def reference() -> str: return MONDO_REFERENCE_NOTES
```

Standard resource family for metadome: `metadome://capabilities`, `metadome://tools`, `metadome://usage`, `metadome://reference`, `metadome://research-use`, `metadome://citation`. (clinvar/sysndd also use `<x>://schema/overview`, `<x>://license`.) The `instructions=` string on the FastMCP instance names these resources for orientation.

---

## 9. Citation contract (`recommended_citation`)

- Every factual record-derived payload carries a **`recommended_citation`** string to be **pasted verbatim** (never paraphrased/fabricated). Built in `services/citation.py`.
- Citations interpolate stable IDs + the loaded upstream **release/version** (freshness anchor). clinvar example:

```python
def recommended_citation(variation_id, vcv_accession, release_date):
    rel = f" ClinVar weekly release {release_date}." if release_date else ""
    return (f"ClinVar (NCBI). VariationID {variation_id} ({vcv_accession})."
            f"{rel} https://www.ncbi.nlm.nih.gov/clinvar/variation/{variation_id}/")
```

- **Token optimization for lists:** instead of repeating the full citation per row, lift a **`citation_template`** (with `{id}` placeholders) into `_meta.citation_template` in minimal/compact mode; the client fills it from each row's IDs.
- The canonical static citation + license live in `constants.py` (`RECOMMENDED_CITATION`, `<X>_LICENSE`) and are surfaced in `build_capabilities()` and the `<x>://citation` resource.

**metadome:** cite the MetaDome paper (Wiel et al., *Hum Mutat* 2019, "MetaDome: Pathogenicity analysis of genetic variants through aggregation of homologous human protein domains", doi:10.1002/humu.23798) + the transcript/gene id + the MetaDome data version. Confirm exact wording during build.

---

## 10. Logging, config/settings, error middleware

- **Logging:** `structlog` via `logging_config.configure_logging()` → returns a bound logger. `log_format` setting `json|console`; Docker forces `json`.
- **Config:** `pydantic-settings` `BaseSettings`, env prefix `METADOME_LINK_`, nested models use `__` delimiter (`METADOME_LINK_DATA__DB_FILENAME`), optional `.env`. `model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore", env_prefix="METADOME_LINK_", env_nested_delimiter="__")`. A module-level singleton `settings = ServerSettings()` is imported across the app. Settings include `host`, `port` (1024–65535, default 8000), `transport` (`unified|http|stdio`), `mcp_path` (`/mcp`), `cors_origins`, `log_level`, `log_format`, and a nested `data:` config.
- **Error handling:** the envelope IS the error middleware (returns structured errors). FastMCP-level handlers (`ArgValidationMiddleware` in mondo; `install_validation_error_handler` + `install_output_validation_error_handler` in clinvar) convert arg-binding / output-schema failures into the same `invalid_input` envelope with `allowed_values`/`hint` (see `build_arg_error_envelope`).
- `mask_error_details=True` on every FastMCP instance (never leak internals).

---

## 11. Caching / rate-limiting / retry / data acquisition (THE METADOME FORK)

Two patterns. Choose by whether you snapshot MetaDome into SQLite or proxy its API live.

### 11.1 Local-index model (mondo, clinvar) — PREFERRED by the fleet
- **Acquisition:** `ingest/downloader.py` does conditional GET (etag/last-modified, 304-aware) of the upstream release; `ingest/builder.py` `build_database(config, ...)` parses into SQLite atomically under a cross-process build lock (`ingest/lock.py`).
- **Serving:** `data/repository.py` opens the SQLite read-only; no network at request time. In-process query cache is configured via `data.cache_size`/`data.cache_tt l` settings.
- **Refresh:** external cron (`metadome-link-data refresh`), or optional in-process scheduler (`data.refresh_enabled`, default OFF, `refresh_interval_hours`).
- **Distribution (clinvar):** publish a prebuilt `<db>.sqlite.zst` to GitHub Releases; `entrypoint` runs `<x>-link-data bootstrap` → download/verify-sha256/atomic-swap (`BUNDLE_URL=latest`, fatal on failure). mondo always builds locally (lazy fallback on failure).

### 11.2 Live-API model (gtex)
- `httpx.AsyncClient` against the remote REST API (`api/client.py`).
- **Rate limiting:** hand-rolled async **token-bucket** (`TokenBucketRateLimiter`, rate r/s + burst), `asyncio.Lock`-guarded. No `tenacity`/`backoff` dependency.
- **Caching:** `async-lru` (LRU + TTL) decorators on client methods.
- **Observability:** `asgi-correlation-id` injects `X-Request-ID` into outbound headers; `record_upstream_call` / `record_rate_limit_wait` metrics.
- Errors map to typed exceptions (`RateLimitError`, `ServiceUnavailableError`) → `rate_limited`/`upstream_unavailable` envelopes.

---

## 12. CI (GitHub Actions) — adopt clinvar's (mondo has NONE)

Three workflows, all `ubuntu-latest`, single Python `3.12` (no matrix), all third-party actions **SHA-pinned with `# vN`**, identical concurrency + least-privilege `permissions: {contents: read}`.

### 12.1 `ci.yml` (verbatim core)
```yaml
name: CI
on: { pull_request: {}, push: { branches: [main] } }
concurrency: { group: "${{ github.workflow }}-${{ github.ref }}", cancel-in-progress: true }
permissions: { contents: read }
jobs:
  quality:
    name: Format, lint, typecheck, tests, and coverage
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha> # v6
      - uses: actions/setup-python@<sha> # v6
        with: { python-version: "3.12" }
      - uses: astral-sh/setup-uv@<sha> # v8.2.0
        with: { enable-cache: true, version: "0.8.7" }
      - run: uv sync --group dev --frozen      # tests use committed fixture; no bulk download
      - run: make ci-local
      - run: make test-cov
```
- `docker.yml`: build-and-validate only (`docker compose config` + `docker build -t metadome-link:ci .`), **no registry push**, path-filtered.
- `security.yml`: CodeQL (`languages: python`, `build-mode: none`, gated on public repo) + `dependency-review-action` (PR-only, `continue-on-error: true`) + weekly `cron: "17 3 * * 1"`.

---

## 13. Testing

- **Framework:** pytest + pytest-asyncio (`asyncio_mode="auto"` → async tests need no marker), pytest-xdist (`-n auto`), pytest-mock, pytest-cov. `respx` for HTTP mocking (downloader unit tests only).
- **Core pattern (no HTTP mocking at the tool layer):** ship a **small real slice** of the upstream file as a checked-in fixture, run the **real ingest builder** into a temp SQLite DB, test against that local DB. Fixture chain (session → function): `built_db` → `repo` → `service` → `facade`.

```python
# tests/conftest.py (clinvar)
FIXTURE = Path(__file__).parent / "fixtures" / "variant_summary_sample.txt"

@pytest.fixture(scope="session")
def built_db(tmp_path_factory):
    d = tmp_path_factory.mktemp("clinvar_data")
    cfg = Settings(DATA_DIR=d, DB_FILENAME="clinvar.sqlite")
    build_database(cfg, source_path=FIXTURE, last_modified="Mon, 01 Jan 2026 00:00:00 GMT")
    return cfg.db_path

@pytest.fixture
def repo(built_db):
    r = ClinVarRepository(built_db); yield r; r.close()

@pytest.fixture
def service(repo): return ClinVarService(repo)

@pytest.fixture
def facade(service): return create_clinvar_mcp(service_factory=lambda: service)
```

- **In-memory FastMCP client** to call tools (no socket/subprocess):
```python
async def call_tool(mcp, name, args):
    from fastmcp import Client
    async with Client(mcp) as client:
        res = await client.call_tool(name, args)
    return getattr(res, "data", None) or res.structured_content
```
- **Assertions** check the envelope: `out["success"] is True`, domain fields, `out["recommended_citation"]`, `out["_meta"]["next_commands"]`, and `out["error_code"]` on the error path.
- `test_e2e.py`: HTTP via in-process `httpx.ASGITransport(app=app)` (`/health`) + MCP via in-memory `fastmcp.Client`; asserts the exact tool set (`EXPECTED_TOOLS`).
- `test_resources.py`: calls resource functions directly + asserts capabilities lists exactly the registered tools.
- **(mondo invariant) `tests/unit/test_output_schemas.py`:** every tool's real output (success + error, all 4 response modes) must validate against its own `output_schema`.
- **Coverage:** `fail_under = 80` (mondo) / `70` (clinvar); `htmlcov` + (clinvar) `coverage.xml`.

---

## 14. Docker / deployment

- **Base:** `python:3.12-slim` (both stages). **Multi-stage:** `builder` installs `build-essential` + `uv`, runs `uv sync --frozen --no-dev --active --no-install-project` into `/opt/venv`; `production` copies `/opt/venv`, `pip install . --no-deps`, drops to non-root system `app` user.
- **Transport default = `unified`** on **port 8000**, `/health` (REST) + `/mcp` (MCP streamable-HTTP). `EXPOSE 8000`; `VOLUME ["/app/data"]`; `HEALTHCHECK curl -f http://127.0.0.1:8000/health`; `ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]` (no CMD).
- **Env (Docker):** flat prefix, e.g. `METADOME_LINK_MCP_TRANSPORT=unified`, `_MCP_HOST=0.0.0.0`, `_MCP_PORT=8000`, `_MCP_PATH=/mcp`, `_DATA_DIR=/app/data`, `_LOG_FORMAT=json`.
- **entrypoint.sh:** build/fetch the data index first (`metadome-link-data bootstrap|refresh`), then `exec` the server (so it's PID 1 for clean SIGTERM). Choose clinvar's fatal-on-failure or mondo's lazy-fallback.
- **`docker-compose.yml`:** local dev — published `${HOST_PORT:-8000}:8000`, `env_file` optional `.env`/`.env.docker`, named data volume, `restart: unless-stopped`, json-file logging, healthcheck.
- **`docker-compose.npm.yml`:** PROD overlay (self-contained, NOT layered) for nginx-proxy-manager: `expose: 8000` only (no host port), `read_only: true`, `tmpfs` scratch, `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]`, `pids_limit`, `init: true`, resource limits, dual networks (internal bridge + external `${NPM_SHARED_NETWORK_NAME:-npm_default}`). Run: `docker compose -f docker/docker-compose.npm.yml --env-file .env.docker up -d --build`.
- The fleet runs each backend as its own container behind nginx-proxy-manager at `https://metadome-link.genefoundry.org/mcp`.

---

## 15. Router federation — registering `metadome-link`

The router (`genefoundry-router`) does **NOT spawn backends**. It is a FastMCP aggregator that proxies each backend's public HTTPS `/mcp` URL and re-exposes tools as `<namespace>_<tool>` behind a `search_tools`/`call_tool` search surface plus pinned entrypoints. Backend↔router auth: **none** (caller auth never forwarded — confused-deputy defense). Transport: **`http` only** (Streamable HTTP).

To register metadome-link, **three mechanical edits** (no code):

**A. `genefoundry-router/servers.yaml`** — append one entry to the `servers:` list (namespace must match `^[a-z0-9]+$` — `metadome`, NOT `metadome-link`):
```yaml
  - { name: metadome,    repo: berntpopp/metadome-link,      url_env: GF_METADOME_URL,    namespace: metadome,    tags: [protein, tolerance, domain, variant], entrypoints: [<canonical_leaf_tool>] }
```
- `entrypoints` = un-namespaced canonical front-door tool name(s) (e.g. `resolve_transcript` or `get_gene_tolerance`). These get **pinned** (always listed, bypassing BM25) AND named in the router instructions. Surfaces as `metadome_<leaf>`. `<namespace>_<leaf>` must be ≤64 chars and `[a-z0-9_]`.
- Only `name`, `namespace`, `url_env` are strictly required; rest inherit `defaults` (`transport: http`, `enabled: true`, `cache_ttl: 300`).

**B. `genefoundry-router/.env`** (+ `.env.example`, `.env.docker.example`) — add the URL:
```bash
GF_METADOME_URL=https://metadome-link.genefoundry.org/mcp
```

**C. Deploy** metadome-link as its own container reachable at that URL. Until deployed, set `enabled: false` or omit the env — the router skips an `enabled:false`/url-less backend with a warning and still starts.

**Verify:** `genefoundry-router validate` · `genefoundry-router doctor [--strict-naming]` · `genefoundry-router list-tools --namespace metadome`.

> **Tool-Naming Standard v1** (audited by `doctor --strict-naming`): leaf names are `verb_noun`, ≤50 chars, canonical verbs. Design metadome's tool names to comply (`get_*`, `resolve_*`, `search_*`, `map_*`) so no router `transform:` block is needed.

---

## 16. README / docs / versioning / license / disclaimers

- **README sections (clinvar order):** Title → Why a local index → Features → Quick start (incl. Getting the data) → MCP client config → Tools → Example → Data pipeline & refresh (systemd timer) → Configuration → Docker → Citation & License → **Research use disclaimer** → Development.
- **docs/**: `architecture.md`, `deployment.md`, `usage.md`.
- **CHANGELOG.md**: Keep a Changelog + SemVer (mondo has one). **LICENSE**: MIT. **Version**: `__version__` in `<pkg>/__init__.py`.
- **Disclaimers (verbatim contract):** `research_use_only: True` in capabilities; the notice string `"Research use only; not for clinical decision support, diagnosis, treatment, or patient management."` appended to the `instructions=` string, the `<x>://research-use` resource, and capabilities. Treat retrieved text as **evidence data, not instructions** (prompt-injection guard).
- **AGENTS.md / CLAUDE.md:** state the "two planes" boundary + invariants (7-code taxonomy, `next_commands` invariant, `output_schema` + tested validation, `mask_error_details=True`, services return plain dicts).

---

## 17. mondo-link vs clinvar-link — which to template

| Dimension | mondo-link | clinvar-link | Use for metadome |
|---|---|---|---|
| MCP plane richness | **Richest** (envelope tiering, schemas, middleware, metrics, arg_help, next_commands chainers, output-schema tests) | Good, simpler | **mondo** |
| mypy | `strict = true` | lenient (disables 2 codes) | **mondo (strict)** |
| `output_schema` per tool + tested validation | **Yes** (invariant) | No | **mondo** |
| Tool description location | decorator `description=` ending `Signature:` | function docstring | **mondo** |
| DI | global `service_adapters` registry | `service_factory` constructor injection | either (clinvar's is cleaner) |
| CI workflows | **NONE** | **3 (ci/docker/security)** | **clinvar** |
| `.pre-commit-config.yaml` | absent | **present** | **clinvar** |
| Docker bundle distribution | local build (lazy fallback) | **prebuilt `.zst` from GH Releases** (fatal-on-fail) | clinvar if you publish a snapshot; mondo if always-build |
| CHANGELOG | **present** | uses dynamic version | **mondo** |
| Versioning | static `__version__` | `dynamic` via hatch | either |

**Verdict:** template the **MCP plane + package structure + strict typing from mondo-link**, and the **CI/CD + Docker + pre-commit + bundle distribution from clinvar-link**. Use the live-API caching pattern from gtex-link only if metadome proxies a live API rather than a local snapshot.

---

## 18. RECOMMENDED file tree for `metadome-link`

```
metadome-link/
├── pyproject.toml  uv.lock  README.md  CHANGELOG.md  LICENSE  AGENTS.md  CLAUDE.md  Makefile
├── .env.example  .env.docker.example  .pre-commit-config.yaml  .dockerignore  .gitignore
├── mcp_server.py  server.py
├── docker/ {Dockerfile, entrypoint.sh, docker-compose.yml, docker-compose.npm.yml, README.md}
├── .github/workflows/ {ci.yml, docker.yml, security.yml}
├── scripts/ {check_file_size.py, check_deployed_freshness.py}
├── docs/ {architecture.md, deployment.md, usage.md}
├── data/                 # gitignored (local-index model)
├── metadome_link/
│   ├── __init__.py  config.py  constants.py  identifiers.py  exceptions.py
│   ├── logging_config.py  buildinfo.py  server_manager.py  app.py
│   ├── data/ {__init__.py, repository.py}                 # local-index model
│   ├── ingest/ {__init__.py, cli.py, downloader.py, builder.py, parser.py, schema.py, lock.py}
│   ├── services/ {__init__.py, metadome_service.py, resolution.py, pagination.py, shaping.py,
│   │              refresh.py, citation.py}
│   └── mcp/
│       ├── __init__.py  facade.py  envelope.py  capabilities.py  resources.py
│       ├── annotations.py  next_commands.py  schemas.py  middleware.py  metrics.py
│       ├── arg_help.py  service_adapters.py
│       └── tools/ {__init__.py, _common.py, discovery.py, <domain>.py, batch.py}
└── tests/ {conftest.py, _fixture_db.py, fixtures/, test_*.py, unit/test_output_schemas.py}
```
*(If metadome uses a live API instead of a local SQLite snapshot: replace `data/` + `ingest/` with `api/ {client.py, routes/}` per gtex, add `async-lru` + token-bucket rate limiter, drop the `metadome-link-data` script and data Docker bootstrap.)*

---

## 19. Checklist — conventions `metadome-link` MUST follow

**Packaging & tooling**
- [ ] hatchling backend; `requires-python = ">=3.12"`; MIT license; commit `uv.lock`; no `.python-version`.
- [ ] Runtime dep floor (§2.2) incl. `fastmcp>=3.2`, `mcp[cli]>=1.27`, `pydantic-settings`, `structlog`, `typer`, `orjson`.
- [ ] Three `[project.scripts]`: `metadome-link`, `metadome-link-mcp`, `metadome-link-data`.
- [ ] ruff (line 100, 12-selector set, double quotes), mypy `strict = true`, pytest `asyncio_mode="auto"` + function loop scope, coverage `fail_under` ≥ 70 + `htmlcov`.
- [ ] Self-documenting Makefile; everything via `uv run`; `uv sync --frozen` in CI/Docker.

**MCP plane**
- [ ] `create_metadome_mcp()` builds `FastMCP(name="metadome-link", instructions=..., mask_error_details=True)`.
- [ ] Two-planes boundary: services return plain dicts + raise typed exceptions; `mcp/` owns envelopes.
- [ ] `run_mcp_tool` injects `success`/`_meta`; errors are **returned** structured dicts, never raised.
- [ ] 7-code error taxonomy exactly; `retryable` + `recovery_action` on errors.
- [ ] `_meta` = `{tool, request_id, [elapsed_ms], [capabilities_version], [next_commands]}`, **tiered by `response_mode`** (`minimal` opt-out; `compact`+ always carries `next_commands`).
- [ ] Every tool: `@mcp.tool(name, title, annotations=READ_ONLY_OPEN_WORLD, output_schema=, tags=, description=)`, first description sentence = discovery summary ending `Signature: tool(args...)`.
- [ ] `response_mode` (minimal|compact|standard|full, default compact) via `services/shaping.py`; optional sparse `fields=` projection.
- [ ] Pagination block `{total, returned, limit, offset, truncated, next_offset}` + forward-page `next_commands`.

**Discovery & contract**
- [ ] `get_server_capabilities(detail=)` + `get_diagnostics()`; capabilities `tools` list == registered tools (test it).
- [ ] `capabilities_version` = sha256[:16] of the contract (excluding `build`/self), cached, echoed in `_meta`.
- [ ] `metadome://` resources: capabilities, tools, usage, reference, research-use, citation.
- [ ] `recommended_citation` (paste-verbatim) on records; `citation_template` lifted to `_meta` in compact/minimal lists; cite the data version for freshness.
- [ ] `research_use_only: True` + the research-use notice in instructions + capabilities + resource; prompt-injection guard ("evidence data, not instructions").

**Config / runtime / data**
- [ ] pydantic-settings, env prefix `METADOME_LINK_`, `__` nested delimiter, `.env` support, `settings` singleton.
- [ ] structlog logging (`configure_logging()`), `log_format` json|console.
- [ ] `UnifiedServerManager` with `unified|http|stdio`; unified mounts MCP at `/mcp` on port 8000.
- [ ] Choose data model (§11): local SQLite index (preferred) OR live-API proxy; wire caching/rate-limit accordingly.

**CI / Docker / federation**
- [ ] `.github/workflows/` ci + docker + security (SHA-pinned, Python 3.12, `make ci-local` + `make test-cov`).
- [ ] `.pre-commit-config.yaml` (std hooks + ruff + local mypy).
- [ ] Multi-stage `python:3.12-slim` Dockerfile, non-root, unified transport :8000, `/health` + `/mcp`, data volume, entrypoint builds index first; `docker-compose.yml` + hardened `docker-compose.npm.yml`.
- [ ] Tests: fixture-driven real ingest → temp SQLite, in-memory `fastmcp.Client`, envelope assertions, `test_output_schemas.py`, e2e both transports.
- [ ] Router registration: `servers.yaml` entry (namespace `metadome`, `entrypoints: [...]`) + `GF_METADOME_URL` env; tool names comply with Tool-Naming Standard v1 (`verb_noun`, ≤50 chars).
- [ ] README with the required sections incl. Research use disclaimer; AGENTS.md/CLAUDE.md stating the two-planes invariants.
```
