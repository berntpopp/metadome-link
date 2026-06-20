# CLAUDE.md

This file orients Claude Code (and other agents) in this repository.

**Read [AGENTS.md](AGENTS.md) first** — it is the authoritative contributor and
agent guide (architecture, invariants, conventions, definition of done). This
file only highlights the essentials.

## Essentials

- `metadome-link` is a read-only MCP + REST server that wraps the **MetaDome** web
  service: per-residue missense tolerance landscapes (`sw_dn_ds`), Pfam domains,
  meta-domain homolog variant aggregation, and gnomAD/ClinVar per-position counts
  for human transcripts (GRCh37/hg19). One backend in the GeneFoundry `-link` fleet.
- **Two planes:** the data plane (`config`/`constants`/`identifiers`/`api`/`cache`/
  `services`) calls MetaDome over async httpx, normalizes, and returns plain dicts;
  the MCP plane (`mcp/`) is domain-agnostic scaffolding (lifted from `mondo-link`)
  where `run_mcp_tool` owns `success`/`_meta` and returns structured errors (never
  raised). There is **no `ingest/` / no local index** — this is a live-API proxy
  with a persistent on-disk result cache + in-memory TTL.
- **Async model:** explicit request + poll split (`request_tolerance_landscape` →
  `get_tolerance_landscape`); `status:"processing"` is a first-class success state.
  Cold builds can take ~1 h; the poll loop never blocks past a soft deadline.
- **Invariants:** every `compact`+ (default) response carries `_meta.next_commands`
  (`minimal` opts out → `_meta = {tool, request_id}`); `_meta.data_versions` is
  ALWAYS present; 7-code error taxonomy; each tool has `output_schema` +
  `READ_ONLY_OPEN_WORLD` and a first sentence ending `Signature: tool(args...)`;
  keep `capabilities.TOOLS` (11 names) in sync; validate transcript ids in
  `identifiers.py` (require the `.N` version); cite Wiel et al. 2019.
- **Definition of done:** `make ci-local` green (format-check, lint-ci, lint-loc
  ≤500 lines/file, mypy strict, tests ≥80% coverage).
- `structlog` → stderr only; stdout is reserved for the stdio MCP protocol.

## Common commands

```bash
make install        # uv sync --group dev
make cache-status   # print on-disk result cache stats + pinned data version
make dev            # unified REST + MCP server
make mcp-serve      # stdio MCP server
make ci-local       # the full gate
```

Research use only; not for clinical decision support. MetaDome data is GRCh37/hg19
(gnomAD r2.0.2, ClinVar 2018-06-03) — historical; use live gnomAD/ClinVar for
current data.

## Two-plane invariants (non-negotiable)

1. **Data plane returns plain dicts; MCP plane owns `success`/`_meta`.** Services raise typed
   exceptions; `run_mcp_tool` catches and returns structured errors. Never build envelopes in
   the data plane; never raise to the MCP client.
2. **`_meta.data_versions` is ALWAYS present** in `compact`+ responses. This is the
   GRCh37/hg19 data-currency caveat surface.
3. **`_meta.next_commands` in every `compact`+ (default) response.** `minimal` explicitly
   opts out.
4. **7-code error taxonomy** (see `metadome_link/exceptions.py`): `invalid_input`,
   `not_found`, `ambiguous_query`, `data_unavailable`, `rate_limited`,
   `upstream_unavailable`, `internal_error`.
5. **`status:"processing"` is a first-class success state** (`success:true`), never an error.
   The poll loop never hard-blocks — soft deadline enforced.
6. **Transcript ids require the `.N` version suffix** (`^ENST\d{11}\.\d+$`). Enforce in
   `identifiers.validate_transcript_id`; never accept bare `ENST…` ids.
7. **`capabilities.TOOLS` (11 names) must equal the registered tool set.** Enforced by
   `tests/test_resources.py`.
8. **Every tool's success and error output validates against its `output_schema`** — enforced
   by `tests/unit/test_output_schemas.py` in all 4 response modes.

## Documentation

- `README.md` — full tool catalog + TP53 workflow example
- `docs/architecture.md` — two-plane + async model + caching
- `docs/deployment.md` — Docker + config reference
- `docs/usage.md` — tool reference + workflows + error codes
- `docs/router-registration.md` — `servers.yaml` entry + `GF_METADOME_URL`
