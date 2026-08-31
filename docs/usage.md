# Usage

## Overview

`metadome-link` exposes 11 MCP tools across 5 functional groups. All tools accept
`response_mode ∈ {minimal, compact, standard, full}` (default `compact`). Errors are returned
as a typed envelope — never raised. Every `compact`+ response carries `_meta.next_commands`
with ready-to-call follow-up tools.

## Tool groups

### 1. Discovery (`mcp/tools/discovery.py`)

#### `get_server_capabilities(detail="summary"|"full", response_mode="compact")`

Cold-start orientation. Returns the server identity, `data_versions` (MetaDome 2.0:
GRCh38.p14 / GENCODE v45 / UniProt 2025_01 / Pfam 37.4 / gnomAD v4.1 /
ClinVar 2025-10-06), the frozen 11-tool list, response
modes, recommended workflows, error codes, limits, and policy notes (research-use + data-currency
caveats). `detail="full"` adds score semantics and provenance policy prose.

Call this first in a cold session, or read `metadome://capabilities`.

#### `get_diagnostics(response_mode="compact")`

Runtime health without calling MetaDome: build info (git sha), cache stats (on-disk + LRU
sizes, pinned data version), metrics snapshot (request/error counts + p50/p95/p99 latency),
data versions, capabilities hash. Use to confirm cache state or diagnose a misconfigured server.

### 2. Transcripts (`mcp/tools/transcripts.py`)

#### `resolve_transcript(query, response_mode="compact")`

Resolve a free-text gene symbol or versioned Ensembl transcript id to MetaDome GRCh38.p14
transcript candidates.

- **Gene symbol** (`TP53`, `BRCA1`): returns all transcripts sorted by `aa_length` descending;
  the longest protein-coding entry is flagged `canonical`. Unknown gene → `not_found`.
- **ENST id** (`ENST00000269305.9`): the `.N` version suffix is required; validated and echoed
  directly without an upstream call. An id without a version suffix → `invalid_input`.

`_meta.next_commands` points at `request_tolerance_landscape` for the canonical transcript.

### 3. Async tolerance landscape (`mcp/tools/landscape.py`)

MetaDome computes landscapes asynchronously. The two-tool split is explicit by design.

#### `request_tolerance_landscape(transcript_id, response_mode="compact")`

Submit (or re-confirm) a landscape build and return a job handle. **Idempotent.**

Returns:
```json
{
  "job_id": "ENST00000269305.9",
  "transcript_id": "ENST00000269305.9",
  "status": "ready",         // or "processing"
  "poll_after_s": 10,
  "eta_hint": "~1 min",
  "cold_build_warning": "..."
}
```

When `status:"ready"`, call `get_tolerance_landscape` immediately. When `status:"processing"`,
poll `get_tolerance_landscape` after `poll_after_s` seconds.

Bad / unversioned transcript id → `invalid_input`.

#### `get_tolerance_landscape(transcript_id, position_start?, position_stop?, limit=200, offset=0, response_mode="compact")`

Cache-first fetch of the built landscape.

- **Cache hit**: returns the landscape immediately.
- **Cache miss + build ready**: fetches from MetaDome, caches on disk, returns the landscape.
- **Cache miss + still building**: returns `{success:true, status:"processing", poll_after_s}`
  — **not an error**. Re-poll after `poll_after_s`.
- **Build failed**: returns `upstream_unavailable` with the stored error summary.

Landscape response (when ready):
```json
{
  "transcript_id": "ENST00000269305.9",
  "gene_name": "TP53",
  "protein_ac": "P04637",
  "refseq_ids": ["NP_000537.3"],
  "domains": [
    { "ID": "PF00870", "Name": "P53", "start": 94, "stop": 292,
      "metadomain": true, "meta_domain_alignment_depth": 2187 }
  ],
  "positional_annotation": [
    { "protein_pos": 1, "ref_aa": "M", "sw_dn_ds": 0.41, "sw_coverage": 0.1, ... }
  ],
  "pagination": { "total": 393, "returned": 200, "limit": 200, "offset": 0,
                  "truncated": true, "next_offset": 200 },
  "data_versions": { "assembly": "GRCh38.p14", "gnomad": "v4.1", ... },
  "recommended_citation": "MetaDome: Pathogenicity analysis ...",
  "success": true
}
```

`position_start` / `position_stop` (1-based, inclusive) slice the landscape for token-efficient
range queries. If omitted, the full `positional_annotation` is paginated.

### 4. Per-position tools (`mcp/tools/positions.py`)

All three operate on a built landscape. A cache miss attempts one live poll; if still building
→ `not_found` with `recovery_action:"switch_tool"` and `next_commands` pointing at
`request_tolerance_landscape` + `get_tolerance_landscape`.

#### `get_position_tolerance(transcript_id, position, response_mode="compact")`

One residue (1-based position): `sw_dn_ds`, `sw_coverage`, codon context, `ref_aa`, genomic
coordinates, domain membership, and explicitly scoped `variant_evidence`. Out-of-range position →
`invalid_input`.

#### `get_variant_counts(transcript_id, position?, position_start?, position_stop?, source="both"|"gnomad"|"clinvar", response_mode="compact")`

Residue-level ClinVar annotations plus separately labelled Pfam meta-domain homolog aggregates.
`variant_evidence.residue_level.gnomad` is always `available:false`: MetaDome does not provide
true per-residue gnomAD counts, so it never reports a misleading zero. Accepts:
- A single position (`position=175`).
- An inclusive range (`position_start=100, position_stop=200`).
- The whole protein (omit all three — paginated).

When `source` includes `clinvar`, each residue's ClinVar variants are listed with `clinvar_ID`
(coerced to str) and an NCBI URL. `residue_level.clinvar.variant_count` matches that list;
`meta_domain_homolog_aggregate` is cross-gene aligned-domain evidence, never this residue's
ClinVar or gnomAD count.

#### `compare_positions(transcript_id, positions, response_mode="compact")`

Side-by-side tolerance table for a batch of residue positions (≤ 50). Returns one row per
position: `protein_pos`, `ref_aa`, `sw_dn_ds`, `domain_ids`, and explicitly scoped
`variant_evidence`.
Out-of-range positions get a per-item error row — the whole batch never fails for one bad
position.

### 5. Domain tools (`mcp/tools/domains.py`)

#### `get_protein_domains(transcript_id, response_mode="compact")`

List the Pfam domains annotated on the transcript's tolerance landscape:

```json
{
  "domains": [
    { "ID": "PF00870", "Name": "P53", "start": 94, "stop": 292,
      "metadomain": true, "meta_domain_alignment_depth": 2187 },
    { "ID": "PF07710", "Name": "P53_tetramer", "start": 325, "stop": 356,
      "metadomain": true, "meta_domain_alignment_depth": 2187 }
  ]
}
```

Requires a built landscape.

#### `get_meta_domain(transcript_id, position, domains?, limit=100, offset=0, response_mode="compact")`

Homologous-domain variant drill-down via MetaDome endpoint 6. Returns per Pfam domain:
`alignment_depth`, `normal_variants[]` (gnomAD, with `gene_name`, AA change, AC/AN), and
`pathogenic_variants[]` (ClinVar, with `gene_name`, AA change, `clinvar_ID` coerced to str).

The `domains` argument (`{PfamID: [consensus_pos, ...]}`) selects which meta-domains to fetch.
**Omit it** to derive the selector automatically from the cached landscape residue's domain map.
A residue with no meta-domain mapping returns empty lists — **not an error**.

Variant lists are paginated via `limit` + `offset`.

### 6. Analysis (`mcp/tools/analysis.py`)

#### `summarize_intolerant_regions(transcript_id, threshold=0.5, min_run=3, top_n=15, response_mode="compact")`

Scan the cached landscape and return the top ranked contiguous intolerant regions:

- A region is a stretch of `min_run` or more consecutive residues with `sw_dn_ds < threshold`.
- Regions are ranked by `mean_sw_dn_ds` ascending (most constrained first).
- Each region is annotated with overlapping Pfam domain IDs, actual summed per-residue ClinVar
  annotations, and separately labelled Pfam homolog aggregates. Region homolog aggregates are
  not unique-variant or transcript-residue counts.

Parameters:
- `threshold` (default 0.5, range 0–2): intolerant residue cutoff.
- `min_run` (default 3, range 1–100): minimum region length.
- `top_n` (default 15, range 1–100): maximum regions returned.

## Worked example: TP53

The canonical five-step pattern for a variant-interpretation query.

**Step 1 — resolve the canonical transcript:**
```json
{ "tool": "resolve_transcript", "arguments": { "query": "TP53" } }
```
Returns all GRCh38.p14 transcripts sorted by length; the longest protein-coding entry is flagged
`canonical`. For TP53 this is `ENST00000269305.9` (393 aa, MANE Select).

**Step 2 — request the landscape:**
```json
{ "tool": "request_tolerance_landscape", "arguments": { "transcript_id": "ENST00000269305.9" } }
```
For TP53 the landscape is pre-built; `status:"ready"` is returned immediately.

**Step 3 — fetch the landscape:**
```json
{ "tool": "get_tolerance_landscape", "arguments": { "transcript_id": "ENST00000269305.9" } }
```
Returns Pfam domains (`PF00870` — P53, `PF07710` — P53_tetramer), paginated
`positional_annotation` (`sw_dn_ds` per residue), and the data version block. If a cold build
is running, `status:"processing"` is returned — re-poll after `poll_after_s`.

**Step 4a — inspect a specific residue (p.R175):**
```json
{ "tool": "get_position_tolerance", "arguments": { "transcript_id": "ENST00000269305.9", "position": 175 } }
```

**Step 4b — meta-domain drill-down at p.175:**
```json
{ "tool": "get_meta_domain", "arguments": { "transcript_id": "ENST00000269305.9", "position": 175 } }
```
Returns ClinVar pathogenic variants observed at the aligned consensus position across all
homologous proteins in the same Pfam domain family.

**Step 4c — identify the most constrained regions:**
```json
{ "tool": "summarize_intolerant_regions", "arguments": { "transcript_id": "ENST00000269305.9" } }
```
Returns ranked contiguous intolerant runs (mean `sw_dn_ds` below threshold) annotated with
overlapping Pfam domains and explicitly scoped variant evidence.

## Recommended workflows

### Gene → canonical transcript

```
resolve_transcript(query="TP53")
  → canonical_transcript_id = "ENST00000269305.9"
```

### Landscape → per-position analysis

```
request_tolerance_landscape(transcript_id="ENST00000269305.9")
  → status:"ready"
get_tolerance_landscape(transcript_id="ENST00000269305.9")
  → landscape + domains + paginated positional_annotation
get_position_tolerance(transcript_id="ENST00000269305.9", position=175)
  → sw_dn_ds at p.R175
get_meta_domain(transcript_id="ENST00000269305.9", position=175)
  → homologous ClinVar pathogenic variants at consensus position
summarize_intolerant_regions(transcript_id="ENST00000269305.9")
  → top constrained regions
```

### Cold-build transcript

```
request_tolerance_landscape(transcript_id="ENST00000000001.1")
  → status:"processing", poll_after_s=30
# wait poll_after_s seconds, then:
get_tolerance_landscape(transcript_id="ENST00000000001.1")
  → status:"processing" (still building)
# repeat until:
get_tolerance_landscape(transcript_id="ENST00000000001.1")
  → landscape (build complete)
```

### Variant comparison

```
compare_positions(transcript_id="ENST00000269305.9", positions=[175, 248, 273])
  → side-by-side table: sw_dn_ds, domain_ids, variant_counts for each position
```

## `response_mode` tiers

| Mode | `_meta` | Payload shaping | Use when |
|------|---------|----------------|----------|
| `minimal` | `{tool, request_id}` only | Identity anchors only | Token-cheapest; machine parsing |
| `compact` (default) | + `next_commands`, `capabilities_version`, `data_versions` | Null/empty fields dropped; lists projected to key fields | Normal agent use |
| `standard` | + `elapsed_ms` | Complete records, structured fields expanded | Debugging |
| `full` | + `elapsed_ms` | Full records, full domain maps, full variant detail | Detailed review |

A hard char-budget guard (~25k tokens) truncates overflow lists and injects `dropped_summary`
when the payload exceeds budget.

## Error codes

| Code | Meaning | `retryable` |
|------|---------|-------------|
| `invalid_input` | Bad argument (unversioned ENST, out-of-range position, validation failure) | false |
| `not_found` | Unknown gene, landscape not yet built, empty result | false |
| `ambiguous_query` | Query matches multiple candidates (returns `candidates` list) | false |
| `data_unavailable` | Data source temporarily unreachable or empty | false |
| `rate_limited` | MetaDome returned HTTP 429 | true |
| `upstream_unavailable` | 5xx / timeout / Celery FAILURE | true |
| `internal_error` | Unexpected server error | false |

On a `not_found` for a missing landscape, `recovery_action` is `"switch_tool"` and
`_meta.next_commands` offers `request_tolerance_landscape` + `get_tolerance_landscape`.

## Limits

| Parameter | Limit |
|-----------|-------|
| Batch positions (`compare_positions.positions`) | ≤ 50 |
| Default page limit (`limit`) | 200 |
| Maximum page limit (`limit`) | 1000 |

## Resources (`metadome://`)

The server exposes a family of static MCP resources for cold-start orientation:

| URI | Content |
|-----|---------|
| `metadome://capabilities` | Full capabilities JSON |
| `metadome://tools` | Tool list + count |
| `metadome://usage` | Usage notes (this document, summary form) |
| `metadome://reference` | MetaDome reference and score semantics |
| `metadome://research-use` | Research-use disclaimer verbatim |
| `metadome://citation` | Recommended citation verbatim |
