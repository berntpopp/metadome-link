# MetaDome API / Data Reference

**Purpose:** Current v2 API reference for the MetaDome MCP wrapper. The older v1 research
capture remains below as historical material and is not evidence for today's endpoint,
build, or provenance contract.
**Target service:** MetaDome 2.0 at `https://www.metadome.app/metadome`, exposing
build-scoped tolerance landscapes, Pfam domains, meta-domain variant aggregation, and
gnomAD/ClinVar per-position counts.

**Current evidence:** direct bounded live checks on **2026-08-31** exercised the v2
`GRCh37.p13` and `GRCh38.p14` namespaces. The authoritative v2 component identities are
the Zenodo 19376150 record: GRCh37 uses GENCODE v19, UniProt 2025-01, Pfam 37.4, gnomAD
r2.0.2, ClinVar 2025-10-06; GRCh38 uses GENCODE v45, UniProt 2025-01, Pfam 37.4, gnomAD
v4.1, ClinVar 2025-10-06.

**Confidence legend:** `CONFIRMED-LIVE` means observed by the current v2 capture below;
`HISTORICAL-CAPTURE` means retained from the obsolete v1 source/live investigation and
must not be used as current production evidence; `SOURCE` is source-only.

> **Historical v1 notice.** The Stuart/Radboudumc URL, unscoped GRCh37 API paths, v1
> response key `trancript_ids`, and 2016/2018 component versions in this document are
> historical capture details only. They are not confirmed-live and are superseded by the
> build-scoped v2 contract documented here.

**Artifacts saved for reference:**
- HAR: `/tmp/metadome.har` (2.6 MB, `content: embed`)
- Newline-delimited request log: `/tmp/metadome-net.log`
- Captured JSON bodies + screenshots: `/tmp/metadome-captures/`
  - `get_transcripts_TP53.json`, `result_TP53_live.json` (142 KB), `metadomain_p175_populated.json`, `01_dashboard.png`
- Capture script: `/tmp/metadome-pw/capture.js`
- Canonical bundled example (older schema variant): `/tmp/metadome-src/metadome/presentation/web/static/json/example_T_gene.json`

---

## 1. Base URL & global facts

| Item | Value | Confidence |
|---|---|---|
| Production base | `https://www.metadome.app/metadome` | CONFIRMED-LIVE |
| API prefix | `https://www.metadome.app/metadome/api` | CONFIRMED-LIVE |
| Web (HTML) prefix | `https://www.metadome.app/metadome` | CONFIRMED-LIVE |
| Blueprint registration | `app.register_blueprint(api_bp, url_prefix='/metadome/api')` and `web_bp` at `/metadome` | SOURCE (`metadome/factory.py`) |
| Static prefix | `/metadome/static` | SOURCE |
| Auth / API key | **None** — fully open, no token | CONFIRMED-LIVE |
| CSRF on API | **None** — API blueprint has no `before_request`/CSRF guard. (Flask-WTF CSRF only protects the HTML contact form.) | SOURCE + CONFIRMED-LIVE |
| CORS headers | None set in source; cross-origin browser use may be blocked by same-origin policy. Server-side (curl/Node) is unaffected. | SOURCE |
| Cookies needed | None for the API. (Site serves a `session` cookie + Google Analytics `G-9JRTWZLPFC`, but API calls succeed without any cookie.) | CONFIRMED-LIVE |
| Content-Type for POST | `application/json` (body read via `request.get_json()`) | CONFIRMED-LIVE |
| Genome build | **GRCh37.p13 or GRCh38.p14**; every API operation is build-scoped. | CONFIRMED-LIVE |
| Reference data versions | Build-specific v2 profiles from Zenodo 19376150 (component identities listed above). | SOURCE + CONFIRMED-LIVE |

---

## 2. Endpoint catalog

All paths below are relative to the v2 API prefix `https://www.metadome.app/metadome/api`.
Source: `metadome/presentation/api/routes.py`.

| # | Method | Path | Body / params | Purpose | Confidence |
|---|---|---|---|---|---|
| 1 | GET | `/get_transcripts/<genome_build>/<gene_name>` | path: exact build + gene symbol | List transcripts for a gene symbol | CONFIRMED-LIVE |
| 2 | POST | `/submit_visualization/` | JSON: `{"transcript_id": "ENST…​.N", "genome_build": "…"}` | Submit the build-scoped async visualization | CONFIRMED-LIVE |
| 3 | GET | `/status/<genome_build>/<transcript_id>` | path: exact build + transcript | Poll async job status | CONFIRMED-LIVE |
| 4 | GET | `/result/<genome_build>/<transcript_id>` | path: exact build + transcript | Fetch the completed tolerance-landscape JSON | CONFIRMED-LIVE |
| 5 | GET | `/error/<genome_build>/<transcript_id>` | path: exact build + transcript | Fetch stored error for a failed job | CONFIRMED-LIVE |
| 6 | POST | `/get_metadomain_annotation/` | JSON: `{transcript_id, protein_position, requested_domains}` | Per-position homologous (meta-domain) variant detail | CONFIRMED-LIVE |

> **Important — trailing slashes are significant.** POST endpoints 2 and 6 use a trailing
> slash. The v2 GET endpoints 1, 3, 4, and 5 use the exact build-scoped paths above without
> a trailing slash.

There is **no** gene-name search/autocomplete endpoint. For v2, treat
`get_transcripts/<genome_build>/<gene>` as both the validity check and transcript lookup;
the response key is `transcript_ids` (empty means unknown gene/no transcript in that build).

---

## 3. Endpoint details (request + representative response)

### 3.1 GET `/get_transcripts/<genome_build>/<gene_name>` — `CONFIRMED-LIVE` (v2)

The exact build token is part of the path. Returns the transcripts for that build; entries
with `has_protein_data=false` cannot be visualized. The wrapper prefers an analyzable
`MANE_Select` transcript when selecting a canonical candidate.

**Request**
```
GET /metadome/api/get_transcripts/GRCh38.p14/TP53
```

**Response (200, real, full):**
```json
{
  "message": "Retrieved transcripts for gene 'TP53'",
  "gene_name": "TP53",
  "genome_build": "GRCh38.p14",
  "transcript_ids": [
    {"aa_length": 393, "gencode_id": "ENST00000269305.9", "has_protein_data": true, "mane_transcript_type": "MANE_Select",
     "refseq_nm_numbers": "NM_000546.5, NM_001126112.2, NM_001126118.1, NM_001276760.1, NM_001276761.1"},
    {"aa_length": 285, "gencode_id": "ENST00000413465.2", "has_protein_data": false, "mane_transcript_type": "", "refseq_nm_numbers": ""},
    {"aa_length": 346, "gencode_id": "ENST00000455263.2", "has_protein_data": true, "mane_transcript_type": "",
     "refseq_nm_numbers": "NM_001126113.2, NM_001276695.1"},
    {"aa_length": 343, "gencode_id": "ENST00000359597.9", "has_protein_data": false, "mane_transcript_type": "", "refseq_nm_numbers": ""},
    {"aa_length": 341, "gencode_id": "ENST00000420246.2", "has_protein_data": true, "mane_transcript_type": "",
     "refseq_nm_numbers": "NM_001126114.2, NM_001276696.1"},
    {"aa_length": 393, "gencode_id": "ENST00000445888.2", "has_protein_data": true, "mane_transcript_type": "", "refseq_nm_numbers": ""}
  ]
}
```

For a nonempty response, `gene_name` is present and matches the normalized requested
gene symbol; only a genuinely empty unknown-gene response may omit that echo.

> **v2 key:** `transcript_ids`. The misspelled `trancript_ids` key belongs only to the
> historical v1 capture and is not accepted by the current client.

**Unknown gene (200, not an error):**
```json
{"message": "No transcripts available in database for gene 'NONEXISTENTGENE123'", "genome_build": "GRCh38.p14", "transcript_ids": []}
```

**Field dictionary (per transcript entry):**
| field | type | meaning |
|---|---|---|
| `gencode_id` | string | Build-specific GENCODE / Ensembl transcript ID **with version suffix**, e.g. `ENST00000269305.9`. This is the `transcript_id` used by all other endpoints. |
| `aa_length` | int | protein length (amino acids) |
| `has_protein_data` | bool | whether a protein/UniProt mapping exists; `false` ⇒ not visualizable |
| `refseq_nm_numbers` | string | comma+space-joined RefSeq `NM_` accessions (may be `""`) |

Client convention: prefer an analyzable `MANE_Select` entry; otherwise use an analyzable
protein-coding entry. `has_protein_data=false` entries are not visualizable.

---

### 3.2 POST `/submit_visualization/` — `CONFIRMED-LIVE` (v2)

Submits an async Celery job to build the full tolerance landscape for the transcript, **unless** it is already built or already running, in which case it's a fast no-op (idempotent). Always echoes the transcript id back on success.

`transcript_id` is validated against the regex `^ENST[0-9]{11}\.[0-9]+$` — **the version suffix (`.N`) is REQUIRED**.

**Request**
```
POST /metadome/api/submit_visualization/
Content-Type: application/json

{"transcript_id": "ENST00000269305.9", "genome_build": "GRCh38.p14"}
```

**Response (200):**
```json
{"transcript_id": "ENST00000269305.9"}
```

**Missing transcript_id (400):** `{"error": "no transcript id"}`
**Malformed transcript_id (400, v2):** `{"error": "not a valid transcript id: NOTATRANSCRIPT"}`

> A 200 here means "accepted/known"; it does **not** mean the result is ready. You must poll
> `/status/<genome_build>/<transcript_id>`. For already-cached transcripts the job is instant.

---

### 3.3 GET `/status/<genome_build>/<transcript_id>` — `CONFIRMED-LIVE` (v2)

**Request**
```
GET /metadome/api/status/GRCh38.p14/ENST00000269305.9
```

**Response (200):**
```json
{"status": "SUCCESS"}
```

**`status` value set** (source: `controllers/job.py::get_visualization_status` + Celery states):
| value | meaning |
|---|---|
| `PENDING` | no job/result/error file exists yet (also Celery's "unknown task") |
| `SENT` | task published to broker (custom state set in `tasks.py::update_sent_state`) |
| `STARTED` / `RECEIVED` / `RETRY` | standard Celery in-progress states (`CELERY_TRACK_STARTED=True`) |
| `SUCCESS` | result file written; call `/result/` |
| `FAILURE` | error file written; call `/error/` |

The status is derived from the upstream job state. Treat unknown/malformed status bodies as
`upstream_unavailable`; do not synthesize `PENDING`.

---

### 3.4 GET `/result/<genome_build>/<transcript_id>` — `CONFIRMED-LIVE` (v2)

Returns the full pre-built visualization JSON (the tolerance landscape + domains + per-position variants). **404** if not yet built.

**Request**
```
GET /metadome/api/result/GRCh38.p14/ENST00000269305.9
```

**Response (200) — TOP LEVEL (real TP53, positional_annotation abbreviated):**
```json
{
  "transcript_id": "ENST00000269305.9",
  "gene_name": "TP53",
  "protein_ac": "P04637",
  "refseq_ids": ["NM_000546.5", "NM_001126112.2", "NM_001126118.1", "NM_001276760.1", "NM_001276761.1"],
  "domains": [
    {"ID": "PF08563", "Name": "P53 transactivation motif", "start": 5,   "stop": 29,  "metadomain": true, "meta_domain_alignment_depth": 1},
    {"ID": "PF00870", "Name": "P53 DNA-binding domain",   "start": 95,  "stop": 288, "metadomain": true, "meta_domain_alignment_depth": 4},
    {"ID": "PF07710", "Name": "P53 tetramerisation motif", "start": 319, "stop": 357, "metadomain": true, "meta_domain_alignment_depth": 3}
  ],
  "positional_annotation": [ /* one entry PER protein residue, length == aa_length (393) */ ]
}
```

**`positional_annotation[i]` — residue WITH a meta-domain mapping (real, p.175):**
```json
{
  "protein_pos": 175,
  "chr": "chr17",
  "chr_positions": "g.7578400-7578402",
  "cdna_pos": "c.523-525",
  "strand": "-",
  "ref_aa": "R",
  "ref_aa_triplet": "Arg",
  "ref_codon": "CGC",
  "sw_dn_ds": 0.0588…,
  "sw_coverage": 1.0,
  "sw_size": 10,
  "domains": {
    "PF00870": {
      "consensus_pos": [81],
      "normal_variant_count": 2,
      "normal_missense_variant_count": 1,
      "pathogenic_variant_count": 2,
      "pathogenic_missense_variant_count": 2
    }
  }
}
```

**`positional_annotation[i]` — residue WITH a ClinVar variant at that position (real, p.35):**
```json
{
  "protein_pos": 35,
  "sw_dn_ds": 0.2685…,
  "domains": {},
  "ClinVar": [
    {"alt": "T", "alt_aa": "F", "alt_aa_triplet": "Phe", "alt_codon": "TTT",
     "clinvar_ID": "12371", "pos": 7579582, "ref": "G", "type": "missense"}
  ]
}
```

A residue may have **no** `domains` mapping (`"domains": {}`), a domain key mapped to `null` (in-domain but no meta-domain context at that position), or a populated object as above. The `ClinVar` array key is **present only when** ≥1 ClinVar variant maps to that residue.

---

### 3.5 GET `/error/<genome_build>/<transcript_id>` — `CONFIRMED-LIVE` (v2)

Returns the stored Python traceback for a `FAILURE` job. (Returns `"unknown"` if no error file.)
```json
{"error": "error running visualization job", "stacktrace": "Traceback (most recent call last): …"}
```
Also: any unhandled exception in the API blueprint returns **500** with `{"error": "<str>", "stacktrace": "…"}`.

---

### 3.6 POST `/get_metadomain_annotation/` — `CONFIRMED-LIVE` (v2)

Given a residue inside a meta-domain, returns the actual homologous gnomAD ("normal") and ClinVar ("pathogenic") variants aggregated from **all homologous protein-domain instances** aligned to the requested consensus position(s). This is the drill-down behind the per-position counts in `/result/`.

`requested_domains` maps Pfam domain ID → list of **consensus positions** (1-based; take these from the `domains[<PF>].consensus_pos` array in the `/result/` payload for the same residue). `protein_position` is the 1-based residue in the queried transcript.

**Request**
```
POST /metadome/api/get_metadomain_annotation/
Content-Type: application/json

{"transcript_id": "ENST00000269305.9", "genome_build": "GRCh38.p14", "protein_position": 175, "requested_domains": {"PF00870": [81]}}
```

**Response (200, real, trimmed to one variant of each kind):**
```json
{
  "PF00870": {
    "alignment_depth": 3,
    "normal_variants": [
      {
        "gene_name": "TP73", "protein_pos": 121,
        "chr": "chr1", "chr_positions": "g.3638732-3638734", "cdna_pos": "c.364-366", "strand": "+",
        "pos": 3638733, "ref": "G", "alt": "A",
        "ref_aa": "R", "ref_aa_triplet": "Arg", "ref_codon": "CGC",
        "alt_aa": "H", "alt_aa_triplet": "His", "alt_codon": "CAC",
        "type": "missense",
        "allele_count": 1.0, "allele_number": 245218.0
      }
    ],
    "pathogenic_variants": [
      {
        "gene_name": "TP63", "protein_pos": 148,
        "chr": "chr3", "chr_positions": "g.189582168-189582170", "cdna_pos": "c.445-447", "strand": "+",
        "pos": 189582168, "ref": "C", "alt": "T",
        "ref_aa": "R", "ref_aa_triplet": "Arg", "ref_codon": "CGG",
        "alt_aa": "W", "alt_aa_triplet": "Trp", "alt_codon": "TGG",
        "type": "missense",
        "clinvar_ID": 6527.0
      }
    ]
  }
}
```

Empty result example (CONFIRMED-LIVE v2, position with no homologous variants):
```json
{"PF08563": {"alignment_depth": 1, "normal_variants": [], "pathogenic_variants": []}}
```

**Validation:** missing `transcript_id` / `protein_position` / `requested_domains` → 400. Note: the source's 400 branch builds a malformed body (`jsonify({"error: …"})` — a set), so rely on the status code, not the body, for these.

**Field notes:** each variant carries the homolog's own `gene_name`, genomic position in
the requested build, cDNA/codon context, and amino-acid change. `normal_variants`
(gnomAD) add `allele_count`/`allele_number` (finite floats); `pathogenic_variants`
(ClinVar) add an integer-valued `clinvar_ID` (the v2 endpoint may serialize it as a
number, while `/result/` serializes it as a decimal digit string). `type` ∈ `missense`,
`synonymous`, `nonsense`.

---

## 4. End-to-end workflow: "tolerance landscape for a gene"

Confirmed live for `TP53` (already cached ⇒ poll returned `SUCCESS` on first check).

1. **Resolve gene → transcripts**
   `GET /metadome/api/get_transcripts/{genome_build}/{GENE}`
   → pick a `transcript_ids[i]` with `has_protein_data == true`, preferring
   `mane_transcript_type == "MANE_Select"`. Take `gencode_id` (for example
   `ENST00000269305.9`). Empty array ⇒ gene unknown / no transcript in that build.

2. **Submit the build (idempotent)**
   `POST /metadome/api/submit_visualization/` with `{"transcript_id": "<gencode_id>", "genome_build": "<genome_build>"}`
   → 200 `{"transcript_id": …}`. (400 ⇒ malformed id; must include `.N` version.)

3. **Poll status until terminal**
   `GET /metadome/api/status/{genome_build}/{transcript_id}` → `{"status": …}`
   - Loop while status ∈ {`PENDING`,`SENT`,`STARTED`,`RECEIVED`,`RETRY`}.
   - Client polling cadence (from `dashboard.js`): **10 s** for the first 5 checks, then **~50 s** thereafter; UI warns a fresh build "may take up to an hour."
   - Stop on `SUCCESS` (→ step 4) or `FAILURE` (→ `GET /error/{genome_build}/{transcript_id}`).

4. **Fetch the result**
   `GET /metadome/api/result/{genome_build}/{transcript_id}` → full landscape JSON (see §3.4). (404 ⇒ not built yet; should not happen after `SUCCESS`.)

5. **(Optional) Per-position homolog drill-down**
   For a residue `p` whose `positional_annotation` entry has a non-null `domains[<PF>]`, read `consensus_pos` (a list) and call
   `POST /metadome/api/get_metadomain_annotation/` with `{transcript_id, protein_position: p, requested_domains: {<PF>: [consensus_pos…]}}`
   → homologous gnomAD + ClinVar variant lists (see §3.6).

**Recommended MCP timeout/poll policy:** allow up to ~10 min wall-clock with exponential-ish backoff (e.g. 5 s × 5, then 15–30 s); surface a "still building" state to the caller for cold transcripts. Popular transcripts are pre-cached and return instantly.

---

## 5. Data model & field dictionary

### 5.1 Identifiers / indexing
- **Transcript id**: build-specific Ensembl/Gencode `ENST` accession **with version** (`ENST\d{11}\.\d+`). This is the primary key for endpoints 2–6.
- **Gene**: HGNC-style symbol, case-insensitive (`get_transcripts`). One gene → many transcripts.
- **Protein**: UniProt accession in `protein_ac` (e.g. `P04637`). RefSeq `NM_` accessions in `refseq_ids`/`refseq_nm_numbers`.
- **Position indexing**: protein positions (`protein_pos`) and meta-domain `consensus_pos` are **1-based**. Genomic coordinates and component versions are build-specific; do not assume GRCh37/hg19 for a GRCh38.p14 request. `cdna_pos` is a pretty `c.<start>-<stop>` string.

### 5.2 Tolerance score (`sw_dn_ds`) — the core metric
- Field `sw_dn_ds` per residue = a **background-corrected missense-over-synonymous (dN/dS-like) ratio** computed over a sliding window, from gnomAD variation.
- Formula (`metrics/GeneticTolerance.py::background_corrected_mosy_score`):
  `((missense+1)/(missense_background+1)) / ((synonymous+1)/(synonymous_background+1))` over the window. `missense`/`synonymous` are observed gnomAD counts; `*_background` are the total possible (all-SNV) counts.
- **Scale & meaning:** continuous, ≥0. **Lower = more intolerant/constrained** (purifying selection, depleted of missense relative to synonymous). **Higher = more tolerant.** In the MetaDome UI ~0.0 is "highly intolerant" and ~≥1.2 "highly tolerant"; ~1.0 ≈ neutral. (Can be `null` on division-by-zero — handle.)
- **Window:** `SLIDING_WINDOW_SIZE = 10` ⇒ window radius 10 → up to 21 residues; `sw_coverage` ∈ (0,1] is the fraction of the full window available (e.g. < 1 near termini); `sw_size` echoes 10.
- **Allele-frequency cutoff:** `ALLELE_FREQUENCY_CUTOFF = 0.0` (all gnomAD variants included).

### 5.3 `/result/` top-level fields
| field | type | meaning |
|---|---|---|
| `transcript_id` | string | echoed Gencode transcript id |
| `gene_name` | string | gene symbol |
| `protein_ac` | string | UniProt accession |
| `refseq_ids` | string[] | RefSeq `NM_` accessions |
| `domains` | object[] | Pfam domains (see 5.4) |
| `positional_annotation` | object[] | one entry per residue, length = protein length (see 5.5) |

### 5.4 Pfam domain object (in top-level `domains[]`)
| field | type | meaning |
|---|---|---|
| `ID` | string | Pfam accession, e.g. `PF00870` |
| `Name` | string | Pfam domain name |
| `start`, `stop` | int | 1-based protein residue span (inclusive) of the domain |
| `metadomain` | bool | true if a usable meta-domain exists (≥2 homologous instances) |
| `meta_domain_alignment_depth` | int | present only when `metadomain=true`; max alignment depth (number of homologous instances aligned) |

### 5.5 `positional_annotation[i]` fields (per residue)
| field | type | meaning |
|---|---|---|
| `protein_pos` | int (1-based) | residue position |
| `chr` | string | e.g. `chr17` |
| `chr_positions` | string | pretty genomic span in the requested build (GRCh37.p13 or GRCh38.p14), `g.<a>-<b>` |
| `cdna_pos` | string | `c.<a>-<b>` cDNA span of the codon |
| `strand` | `"+"`/`"-"` | gene strand |
| `ref_aa`, `ref_aa_triplet` | string | reference residue (1-letter / 3-letter) |
| `ref_codon` | string | reference codon, e.g. `CGC` |
| `sw_dn_ds` | float\|null | tolerance score (§5.2) |
| `sw_coverage` | float | window coverage fraction |
| `sw_size` | int | window radius (10) |
| `domains` | object | map `PfamID → (null \| meta-domain entry)`; `{}` if no domain covers this residue |
| `ClinVar` | object[] | present only if ≥1 ClinVar variant at this residue (see 5.7) |

**Meta-domain entry** (value inside `domains[<PF>]` when non-null):
| field | type | meaning |
|---|---|---|
| `consensus_pos` | int[] (1-based) | Pfam HMM consensus column(s) this residue aligns to |
| `normal_variant_count` | int | # distinct gnomAD variants across homologous positions (excludes this codon) |
| `normal_missense_variant_count` | int | subset that are missense |
| `pathogenic_variant_count` | int | # ClinVar variants across homologous positions |
| `pathogenic_missense_variant_count` | int | subset that are missense |

> **Schema-drift caution:** the bundled `static/json/example_T_gene.json` is an **older** schema where the meta-domain entry has `consensus_pos` as a **scalar** plus an `other_codons` array, and lacks `*_variant_count`. The **live production** schema (and current `tasks.py`) uses `consensus_pos` as a **list** plus the four `*_variant_count` fields above and no `other_codons`. Implement against the live schema; tolerate the legacy shape if reading the example file.

### 5.6 gnomAD ("normal") variant object — from `get_metadomain_annotation` `normal_variants[]`
`gene_name, protein_pos, chr, chr_positions, cdna_pos, strand, pos, ref, alt, ref_aa, ref_aa_triplet, ref_codon, alt_aa, alt_aa_triplet, alt_codon, type` + `allele_count` (float), `allele_number` (float). Allele frequency = `allele_count/allele_number`.

### 5.7 ClinVar ("pathogenic") variant object
- In `/result/` `positional_annotation[i].ClinVar[]`: `alt, alt_aa, alt_aa_triplet, alt_codon, pos, ref, type, clinvar_ID` (`clinvar_ID` is a **string** here).
- In `get_metadomain_annotation` `pathogenic_variants[]`: same fields as gnomAD object minus allele fields, plus `clinvar_ID` (**float** here, e.g. `6527.0`).
- `clinvar_ID` is the ClinVar VariationID → `https://www.ncbi.nlm.nih.gov/clinvar/variation/<id>/`.
- `type` ∈ {`missense`, `synonymous`, `nonsense`}.

---

## 6. Async / latency / rate-limit notes & gotchas

- **Async build pattern:** `submit_visualization` enqueues a **Celery** task (`create_prebuild_visualization`, broker RabbitMQ, result backend Redis). Results are cached on disk per transcript (`metadome_visualization/<ENST>/metadome_visualization.json`); a `visualization_task` file tracks the running task id and a `visualization_error` file captures failures. Subsequent submits/results for the same transcript are served from cache (idempotent, instant). Meta-domain alignments are also cached/prebuilt (`RECONSTRUCT_METADOMAINS=False`).
- **Cold-build latency:** can be tens of seconds to (per UI copy) **up to an hour** for a never-built transcript (it computes Pfam HMM alignments, BLAST, gnomAD/ClinVar tabix queries, etc.). Popular genes are pre-cached. Poll patiently with backoff; do **not** treat a long `PENDING` as failure.
- **Rate limiting:** none observed in source or live; no `Retry-After`/429 seen. Be a good citizen — serialize submissions and avoid hammering `/status/` faster than ~5–10 s.
- **No CSRF/cookies/headers required** for the API; only `Content-Type: application/json` on POSTs. Works fine from server-side HTTP clients (curl/Node/Python).
- **Key gotchas for implementers:**
  - v2 JSON key is `transcript_ids` (the misspelled `trancript_ids` is historical only).
  - Transcript ids **must include the `.N` version suffix** or `submit` returns 400.
  - Trailing slashes are required on POST endpoints 2 and 6; v2 GET paths are build-scoped and have no trailing slash.
  - `clinvar_ID` type is inconsistent (string in `/result/`, float in metadomain) — coerce.
  - 400 bodies on `get_metadomain_annotation` are malformed; trust the status code.
  - All genomic coordinates belong to the requested `GRCh37.p13` or `GRCh38.p14` namespace.
  - A `null` `sw_dn_ds` is possible; `domains` can be `{}` or contain `null` values.
  - Unknown gene returns **200 with empty list**, not 404.

---

## 7. Citation (recommended_citation contract)

Every MetaDome-derived answer should cite the MetaDome web server article. Paste verbatim:

> **MetaDome: Pathogenicity analysis of genetic variants through aggregation of homologous human protein domains.** Laurens Wiel, Coos Baakman, Daan Gilissen, Joris A. Veltman, Gert Vriend and Christian Gilissen. *Human Mutation.* 2019; 40(8): 1030–1038. doi:[10.1002/humu.23798](https://doi.org/10.1002/humu.23798)

Underlying meta-domain method: Wiel et al., *Human Mutation* 2017, doi:[10.1002/humu.23313](https://doi.org/10.1002/humu.23313).
The historical v1 app capture observed web server version `1.0.1`; it is retained only for
method provenance. Current v2 production evidence is the build-scoped service at
<https://www.metadome.app/metadome> and the Zenodo 19376150 component profiles above.

---

## 8. Reference artifact paths (this capture)
- HAR: `/tmp/metadome.har`
- Net log: `/tmp/metadome-net.log`
- Captured bodies: `/tmp/metadome-captures/` (`get_transcripts_TP53.json`, `result_TP53_live.json`, `metadomain_p175_populated.json`, screenshots)
- Capture driver: `/tmp/metadome-pw/capture.js`
- Source clone: `/tmp/metadome-src` (routes: `metadome/presentation/api/routes.py`; builder: `metadome/tasks.py`; job control: `metadome/controllers/job.py`; tolerance metric: `metadome/domain/metrics/GeneticTolerance.py`; client workflow: `metadome/presentation/web/templates/js/dashboard.js`)
