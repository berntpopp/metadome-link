# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Re-vendored the behaviour conformance gate from genefoundry-router `ba09fdc`
  (`docs/conformance/behaviour.py` blob `30d639242b`) so live MCP contract checks
  treat not-found example probes as inconclusive instead of failures.

## [0.2.0] - 2026-07-15

MCP contract-hardening sweep — GeneFoundry fleet standards
(genefoundry-router#73 Tool-Surface Budget, #75 Tool-Schema Documentation, #76
Response-Envelope). Verified against a locally-running server with the vendored
behaviour gate (`tests/conformance/behaviour.py`, byte-identical to router
`791363c`): NON-CONFORMANT (19 fail, 2 UNGATED) → CONFORMANT (0 fail, 0 UNGATED).

### Changed

- **BREAKING (error taxonomy): the `error_code` enum is closed to the fleet's six
  values** — `invalid_input`, `not_found`, `ambiguous_query`, `upstream_unavailable`,
  `rate_limited`, `internal`. The two off-enum codes are mapped at the single
  classification chokepoint: `data_unavailable` → `upstream_unavailable` and
  `internal_error` → `internal`. Discovery (`get_server_capabilities`, the
  `metadome://` reference notes) is updated to advertise the same six.
- **Error envelopes now carry MCP `isError: true`.** A tool error is returned as
  `ToolResult(structured_content=<envelope>, is_error=True)` at both chokepoints —
  the `run_mcp_tool` error boundary and the argument-validation middleware — so a
  client that branches on `isError` sees the failure instead of a silent success.
  The structured envelope (`success:false`, `error_code`, `message`, …) is unchanged.
- **`response_mode="minimal"` no longer empties a result.** It kept only
  `transcript_id`/`gene_name`, so it silently deleted `get_meta_domain`'s
  `meta_domains` collection, `get_position_tolerance`'s scalar results
  (`protein_pos`/`ref_aa`/`sw_dn_ds`), `request_tolerance_landscape`'s poll handle
  (`job_id`/`status`/`poll_after_s`), and every response's mandatory
  `recommended_citation` — all at `success:true` and therefore unusable. `minimal`
  now keeps the mandatory envelope + identifiers and **every essential result**
  (scalars, collections, and `recommended_citation`), dropping only verbose/redundant
  prose (`data_currency_caveat`, already carried in every `_meta`) and null/empty
  values (Response-Envelope v1: a verbosity mode narrows a payload, it must never
  empty a result). Surfaced by the behaviour gate once `get_meta_domain` became
  probeable.

### Removed

- **`outputSchema` is no longer advertised on any tool** (`output_schema=None` on all
  11 tools; `FastMCP(dereference_schemas=False)`). It is an optional field the model
  never reads and was 38% of the surface. Total tool surface drops **6,585 → 4,016
  tokens**; `structuredContent` is unaffected (every tool returns a dict envelope).

### Fixed

- **Schema documentation reaches 100%.** The required `position` argument
  (`get_position_tolerance`, `get_meta_domain`) now carries an `examples` value, so
  the behaviour gate can construct a valid call (was UNGATED / S2). `position_start`
  and `position_stop` on `get_tolerance_landscape` now surface their `description` at
  the property level (the `Field` wraps `int | None` instead of nesting under
  `anyOf`). doc% 95 → 100.

## [0.1.9] - 2026-07-14

### Changed

- **The NPM deployment pulls the released image instead of building from source.**
  `docker/docker-compose.npm.yml` carried `build:`, so a deploy rebuilt the image on the
  server even though CI had already published an attested, digest-addressable image to
  GHCR. It now requires `METADOME_LINK_IMAGE` pinned to a digest and fails closed when it
  is unset. Nothing else in the overlay changed: `container_name`, the Compose project
  name, the healthcheck, networks and volumes are all preserved, so the deployed topology
  and the persisted SQLite result cache are untouched.

## [0.1.8] - 2026-07-13

### Build

- Re-pin the central container CI and release callers to the fixed GeneFoundry
  release standard (`58d011d`), which corrects seven latent defects in the
  reusable workflows. No runtime or MCP surface changes. Research use only; not
  for clinical decision support.

## [0.1.7] - 2026-07-13

### Build

- Adopt the GeneFoundry container-release standard: add SHA-pinned central
  container CI/release callers, typed `container-release.json`, digest-only
  production Compose, complete OCI image labels, normalized Docker context
  exclusions, and the standard `/data` runtime-cache mount. Research use only;
  not for clinical decision support.

## [0.1.6] - 2026-07-12

### Fixed

- Release the HTTP policy v1 remediation, including bounded retries, redirect
  handling, and upstream request safety controls. Research use only; not for
  clinical decision support.

## [0.1.5] - 2026-07-11

### Security

- Guard the FastMCP-core not-found reflection surface (Response-Envelope v1.1
  fast-follow). FastMCP core echoed the caller's own requested tool name /
  resource URI / prompt name (and any control/zero-width/bidi/NUL code points it
  carried) back to the caller and to logs before backend middleware ran. A new
  layered guard (`metadome_link/mcp/notfound_guard.py`) closes it with fixed,
  input-free constants: Layer 1 `on_call_tool` registry preflight (unknown tool
  -> fixed name-free `not_found` envelope, no `_meta.tool` echo), Layer 2
  `on_read_resource` boundary (fixed URI-free `ResourceError`), Layer 3 protocol
  backstop wrapping the raw CallTool/ReadResource/GetPrompt handlers (covers the
  unknown-prompt surface and the unknown-tool return path), and Layer 5 a
  validation-log scrub filter attached to the FastMCP/MCP-SDK source loggers,
  root, and FastMCP's own Rich handlers. Caller self-reflection surface; research
  use only.

## [0.1.4] - 2026-07-11

### Security

- Defense in depth: caller-visible error messages are sanitized of
  control/zero-width/bidi/NUL code points, the upstream MetaDome error body is no
  longer echoed, the arg-validation frame maps to fixed reasons and strips the
  argument name, and the batch-row error is sanitized. Research use only.

## [0.1.3] - 2026-07-11

### Security

- Re-enable FastMCP 3.4.4 strict Host/Origin (DNS-rebinding) protection with configurable
  `ALLOWED_HOSTS` / `ALLOWED_ORIGINS` allowlists (default loopback-only).

## [0.1.2] - 2026-07-03

### Fixed

- Single-source versioning: `metadome_link.__version__` now derives from the
  installed package metadata (`importlib.metadata.version`) instead of a
  hardcoded string, so the version lives only in `pyproject.toml`. The MCP
  `initialize` response now advertises the package version in
  `serverInfo.version` (via `FastMCP(version=__version__)`) rather than the
  FastMCP framework version. `/health` already reported the package version.

### Changed

- Fleet disclaimer standardization: the per-call research-use disclaimer
  (`_meta.unsafe_for_clinical_use = True`) is now emitted on every tool
  response -- success and error paths alike -- at every `response_mode`
  (`minimal | compact | standard | full`), instead of only in
  `get_server_capabilities`.

## [0.1.1] - 2026-06-29

### Security

- Adopt GeneFoundry Container & Deployment Hardening Standard v1: digest-pinned base
  image, hardened `prod` compose overlay (read-only rootfs, `cap_drop: ALL`,
  `no-new-privileges`, `init`, resource limits, expose-only), CORS no longer combines
  wildcard origins with credentials, and a CI container scan (Trivy) + SBOM workflow.

## [0.1.0] - 2026-06-20

### Added

- Initial release of `metadome-link`.
- **11 MCP tools** across 5 functional groups:
  - Discovery: `get_server_capabilities`, `get_diagnostics`
  - Transcripts: `resolve_transcript`
  - Landscape: `request_tolerance_landscape`, `get_tolerance_landscape`
  - Positions: `get_position_tolerance`, `get_variant_counts`, `compare_positions`
  - Domains: `get_protein_domains`, `get_meta_domain`
  - Analysis: `summarize_intolerant_regions`
- Explicit async request + poll model for MetaDome Celery-backed landscape builds.
  `status:"processing"` is a first-class success state carrying `poll_after_s` /
  `eta_hint`; no tool ever hard-blocks.
- On-disk SQLite result cache keyed `(transcript_id, metadome_data_version)`;
  in-memory TTL/LRU cache for transcript lists.
- Async httpx MetaDome client with token-bucket politeness limiter, jittered backoff,
  and typed exception mapping.
- Typed 7-code error taxonomy: `invalid_input`, `not_found`, `ambiguous_query`,
  `data_unavailable`, `rate_limited`, `upstream_unavailable`, `internal_error`.
- `response_mode` ∈ `minimal | compact | standard | full` (default `compact`);
  `_meta.next_commands` on every `compact`+ response.
- `_meta.data_versions` on every response (GRCh37 / Gencode v19 / gnomAD r2.0.2 /
  ClinVar 2018-06-03 / Pfam 30.0).
- `recommended_citation` (verbatim Wiel et al. 2019) on every record-derived payload.
- Unified transport: FastAPI `/health` + MCP `/mcp` on port 8000; stdio and HTTP-only
  transports also supported.
- `metadome://` resource family: `capabilities`, `tools`, `usage`, `reference`,
  `research-use`, `citation`.
- Output-schema invariant test (`tests/unit/test_output_schemas.py`) validating every
  tool's success and error output against its declared `output_schema` in all 4 modes.
- CI: GitHub Actions `ci.yml` (quality gate), `docker.yml` (build validation),
  `security.yml` (CodeQL + dependency review).
- Docker: multi-stage `python:3.12-slim` image, non-root, unified server on `:8000`,
  cache volume at `/app/data`, `docker-compose.yml` + `docker-compose.npm.yml` (production
  nginx-proxy-manager overlay).
- `metadome-link-cache` CLI: `status` / `clear` / `warm` subcommands.
- Full documentation: `README.md`, `CHANGELOG.md`, `docs/architecture.md`,
  `docs/deployment.md`, `docs/usage.md`, `docs/router-registration.md`.

[Unreleased]: https://github.com/berntpopp/metadome-link/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/berntpopp/metadome-link/compare/v0.1.0...v0.1.4
[0.1.0]: https://github.com/berntpopp/metadome-link/releases/tag/v0.1.0
