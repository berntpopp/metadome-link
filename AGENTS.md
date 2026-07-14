# AGENTS.md — metadome-link

Guidance for agents and contributors working in this repository.

> `README.md` is the front door and follows the **GeneFoundry README Standard v1** (hard
> ceiling 200 lines, fixed section order, machine-checked by `scripts/check_readme.py`).
> Depth lives in `docs/` — see the documentation index at the bottom of this file. Do not
> grow the README: relocate.

## What this is

`metadome-link` is a read-only MCP + REST server that wraps the **MetaDome** web
service (Wiel et al., *Human Mutation* 2019). It exposes, per human protein
transcript: the per-residue missense **tolerance landscape** (`sw_dn_ds`, lower =
more intolerant), **Pfam domain** annotations, **meta-domain** (homolog) variant
aggregation, and per-position gnomAD/ClinVar counts (GRCh37/hg19). It is one
backend in the GeneFoundry `-link` fleet, federated behind `genefoundry-router`
under the namespace **`metadome`**. It mirrors the sibling fleet stack lifted from
`mondo-link` (MCP plane) and `mavedb-link` (async API client + TTL cache).

## Two planes (non-negotiable boundary)

- **Data plane** — `config.py`, `constants.py`, `identifiers.py`, `exceptions.py`,
  `api/`, `cache/`, `services/`. Talks to MetaDome over async httpx, normalizes the
  responses, and **returns plain dicts**. It raises typed exceptions from
  `metadome_link.exceptions`; it never builds error envelopes. Unlike most fleet
  siblings there is **no `ingest/` step and no local SQLite index of all data** —
  MetaDome has no bulk dump, so this is a **live-API proxy + persistent result
  cache** (gtex/mavedb pattern). Completed landscapes are cached on disk (SQLite,
  keyed `(transcript_id, metadome_data_version)`); transcript lists use an
  in-memory TTL cache; `/status` is never cached.
- **MCP plane** — `mcp/`. Domain-agnostic scaffolding shared with siblings (lifted
  from `mondo-link`). `run_mcp_tool` (in `mcp/envelope.py`) owns `success` / `_meta`
  and converts exceptions into **returned** structured errors (never raised to the
  client).

## Async model

MetaDome builds landscapes asynchronously (Celery; a cold build can take ~1 h).
The tool surface is an explicit **request + poll split**:
`request_tolerance_landscape(transcript_id)` submits and returns a job handle;
`get_tolerance_landscape(...)` polls/returns the landscape. `status:"processing"`
is a **first-class success state** (not an error), carrying `poll_after_s` /
`eta_hint`. No tool ever hard-blocks: the poll loop is bounded by a soft deadline.

## Invariants

- Services return plain dicts; the envelope owns `success`/`_meta` and returns
  structured errors. **7-code error taxonomy**: `invalid_input`, `not_found`,
  `ambiguous_query`, `data_unavailable`, `rate_limited`, `upstream_unavailable`,
  `internal_error`.
- Every `compact` (default) or richer response carries `_meta.next_commands`
  (ready-to-call follow-ups); `minimal` is the explicit opt-out and returns only
  `_meta = {tool, request_id}`. `_meta` verbosity is tiered by `response_mode`:
  `compact` keeps `next_commands` + `capabilities_version` but drops `elapsed_ms`;
  `standard`/`full` add `elapsed_ms`.
- **`_meta.data_versions` is ALWAYS present** (GRCh37, Gencode v19, gnomAD r2.0.2,
  ClinVar 2018-06-03, Pfam 30.0) — the hg19/data-currency caveat surface.
- Every tool declares `output_schema` + `READ_ONLY_OPEN_WORLD` annotations, and its
  first description sentence is a discovery summary ending with
  `Signature: tool(args...)`.
- **Every tool's real output (success + error, all response modes) must validate
  against its own `output_schema`** — enforced by `tests/unit/test_output_schemas.py`.
- `response_mode` ∈ `minimal | compact | standard | full` (default `compact`). List
  tools also carry a pagination block (`total`/`returned`/`limit`/`offset`/
  `truncated`/`next_offset`); when truncated, `_meta.next_commands` offers a
  forward-page step (advance `offset`). `positional_annotation` and meta-domain
  variant lists are always paginated.
- Every record-derived payload carries `recommended_citation` (verbatim Wiel 2019).
- Keep `mcp/capabilities.py::TOOLS` (the frozen 11-name list) in sync with the
  registered tool set.
- Identifiers are normalised/validated in `identifiers.py` (Ensembl transcript ids
  must carry a `.N` version: `^ENST\d{11}\.\d+$`).
- MetaDome data is **GRCh37/hg19, gnomAD r2.0.2, ClinVar 2018-06-03** — historical.
  Surface the data-currency caveat; do not present counts as current.

## Definition of done

`make ci-local` must be green:

```
format-check   ruff format --check
lint-ci        ruff check
lint-loc       scripts/check_file_size.py   (≤ 500 lines/file, hard cap)
lint-readme    scripts/check_readme.py      (README Standard v1)
typecheck      mypy --strict
test-fast      pytest -n auto, coverage ≥ 80%
```

`tests/unit/test_output_schemas.py` runs inside `test-fast` (every tool's real
output — success and error, all response modes — must validate against its own
`output_schema`). `tests/unit/test_readme_tools.py` asserts the README's `## Tools`
table matches the registered tool set exactly — **add a tool, update the table**, or
CI fails.

## Make targets

```
make install          # uv sync --group dev
make ci-local         # the definition-of-done gate (see above)
make test             # pytest, unit only
make test-fast        # pytest -n auto
make test-integration # live MetaDome endpoint tests (opt-in)
make test-cov         # pytest --cov (coverage ≥ 80%)
make dev              # unified REST + MCP server on 127.0.0.1:8000
make mcp-serve        # stdio MCP server
make cache-status     # on-disk result cache stats + pinned data version
make cache-clear      # drop all cached landscapes
make cache-warm GENES="TP53 BRCA1"   # pre-warm popular transcripts
make docker-up        # Docker stack; make docker-url prints the MCP URL
```

Unit tests are network-free: **respx** mocks the 6 MetaDome endpoints against recorded
fixtures in `tests/fixtures/`. `scripts/check_readme.py` is vendored verbatim from
`genefoundry-router` — keep it byte-identical (it is exempted from `B905` in
`pyproject.toml` rather than edited).

## Conventions

- Python 3.12+, `uv`, hatchling. Add deps via `pyproject.toml`, then `uv lock`.
- `structlog` logs to **stderr only** — stdout is reserved for the stdio MCP
  protocol. Never `print` to stdout outside the CLI.
- Files stay under 500 lines; split by responsibility, not layer.
- TDD: write the failing test first. Unit tests mock the 6 MetaDome endpoints with
  **respx** against recorded fixtures under `tests/fixtures/`.
- Frozen contracts: the `mcp/` scaffolding, the `MetaDomeClient` 6-endpoint +
  `poll_until_ready` signatures, and the `MetaDomeService` / `ResultCache`
  signatures are the seams other modules code against — change them deliberately.

## Layout

```
metadome_link/
  config, constants, identifiers, exceptions, logging_config, buildinfo, app
  server_manager                # unified | http | stdio transports
  api/      client, models       # async httpx MetaDome client (6 endpoints + poll loop)
  cache/    store                # SQLite result cache + in-memory TTL
  services/ metadome_service, resolution, landscape, pagination, shaping, citation
  mcp/      envelope, capabilities, annotations, schemas, next_commands, metrics,
            middleware, facade, arg_help, resources, service_adapters, tools/
server.py  mcp_server.py  scripts/check_file_size.py
```

Research use only; not for clinical decision support, diagnosis, treatment, or
patient management. MetaDome code is MIT; cite Wiel et al. 2019 (doi:10.1002/humu.23798).

## Documentation index

| Doc | Purpose |
|-----|---------|
| `README.md` | Front door (Standard v1): what/why, quick start, tool table, provenance & citation |
| `docs/architecture.md` | Two-plane design, async request+poll model, caching, error taxonomy, envelope |
| `docs/deployment.md` | Docker, full env-var reference, transports + MCP client config, Host/Origin, cache management |
| `docs/usage.md` | Tool-by-tool reference, TP53 worked example, workflows, response_mode tiers, error codes, limits |
| `docs/router-registration.md` | Exact `servers.yaml` entry, `GF_METADOME_URL`, verify commands |
| `CHANGELOG.md` | Version history |
