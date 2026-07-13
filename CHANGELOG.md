# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
