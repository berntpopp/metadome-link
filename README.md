# metadome-link

A read-only MCP/API server that wraps the [MetaDome](https://stuart.radboudumc.nl/metadome)
web service (Wiel et al., *Human Mutation* 2019) and exposes per-protein-position
missense tolerance (`sw_dn_ds`) landscapes, Pfam domains, meta-domain homolog
variant aggregation, and gnomAD/ClinVar per-position counts for human transcripts.
It is one backend in the GeneFoundry `-link` fleet (namespace `metadome`).

> **Research use only**; not for clinical decision support, diagnosis, treatment,
> or patient management. MetaDome data are **GRCh37/hg19** (gnomAD r2.0.2, ClinVar
> 2018-06-03, Gencode v19, Pfam 30.0) — historical; use live gnomAD/ClinVar for
> current data.

See [AGENTS.md](AGENTS.md) for architecture and contributor conventions. Full
documentation (quick start, tool catalog, Docker, citation) is added in a later
task.

## Quick start

```bash
make install      # uv sync --group dev
make ci-local     # format-check, lint, mypy --strict, tests
```

## Citation & license

metadome-link is MIT licensed. MetaDome software is MIT
(https://github.com/laurensvdwiel/metadome). Cite:

> MetaDome: Pathogenicity analysis of genetic variants through aggregation of
> homologous human protein domains. Wiel L, Baakman C, Gilissen D, Veltman JA,
> Vriend G, Gilissen C. Human Mutation. 2019;40(8):1030-1038. doi:10.1002/humu.23798
