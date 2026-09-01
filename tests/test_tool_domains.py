"""Domain tool tests through the real FastMCP facade (Task 12).

These exercise the full MCP path: facade -> envelope -> domain tool body ->
injected (respx-mocked) service -> respx-mocked MetaDome endpoints.

Coverage:
- ``get_protein_domains`` returns the landscape's top-level Pfam ``domains[]``
  (ID/Name/start/stop/metadomain) plus ``next_commands`` chaining.
- ``get_meta_domain`` for the populated residue p.175 with ``domains`` OMITTED
  derives the request from the cached residue and returns homologous
  ``normal_variants`` / ``pathogenic_variants`` carrying the homolog
  ``gene_name``, plus a pagination block.
- A residue with no meta-domain mapping returns empty variant lists -- NOT an
  error.
"""

from __future__ import annotations

from typing import Any

TID = "ENST00000269305.9"


async def test_get_protein_domains_returns_pfam_list(facade: Any, call_tool: Any) -> None:
    """get_protein_domains returns the Pfam domains with ID/Name/start/stop/metadomain."""
    data = await call_tool(facade, "get_protein_domains", {"transcript_id": TID})
    assert data["success"] is True
    assert data["transcript_id"] == TID
    domains = data["domains"]
    assert isinstance(domains, list) and domains
    pf00870 = next(d for d in domains if d["ID"] == "PF00870")
    assert pf00870["Name"] == "P53 DNA-binding domain"
    assert pf00870["start"] == 95
    assert pf00870["stop"] == 288
    assert pf00870["metadomain"] is True
    # compact responses chain via next_commands.
    assert data["_meta"]["next_commands"]


async def test_get_meta_domain_derives_request_when_omitted(facade: Any, call_tool: Any) -> None:
    """get_meta_domain(p.175) with domains omitted derives the request from the residue."""
    data = await call_tool(
        facade,
        "get_meta_domain",
        {"transcript_id": TID, "position": 175},
    )
    assert data["success"] is True
    assert data["protein_position"] == 175
    # Derived from the cached residue's domains map: {PF00870: [81]}.
    assert data["requested_domains"] == {"PF00870": [81]}
    meta = data["meta_domains"]["PF00870"]
    assert meta["alignment_depth"] == 3
    # Homologous variants carry the homolog gene_name (TP63 / TP73), not TP53.
    homolog_genes = {v["gene_name"] for v in meta["normal_variants"]}
    homolog_genes |= {v["gene_name"] for v in meta["pathogenic_variants"]}
    assert homolog_genes <= {"TP63", "TP73"}
    assert meta["normal_variants"]
    assert meta["pathogenic_variants"]
    # Pagination block present (per variant-list).
    assert "pagination" in meta
    assert "normal_variants" in meta["pagination"]
    assert "pathogenic_variants" in meta["pagination"]


async def test_get_meta_domain_non_metadomain_position_empty_not_error(
    facade: Any, call_tool: Any
) -> None:
    """A residue with no meta-domain mapping returns empty meta_domains, not an error."""
    # p.2 exists in the trimmed fixture but carries no ``domains`` map -> no
    # upstream metadomain call, empty result (success, NOT an error). Use
    # ``standard`` mode so the empty selector/result dicts survive projection
    # (compact mode drops empty {} values).
    data = await call_tool(
        facade,
        "get_meta_domain",
        {"transcript_id": TID, "position": 2, "response_mode": "standard"},
    )
    assert data["success"] is True
    assert data["protein_position"] == 2
    assert data["requested_domains"] == {}
    assert data["meta_domains"] == {}
    assert "error_code" not in data


async def test_get_meta_domain_explicit_domains_paginates(facade: Any, call_tool: Any) -> None:
    """Explicit domains + limit=1 returns one variant per list and a pagination block."""
    data = await call_tool(
        facade,
        "get_meta_domain",
        {
            "transcript_id": TID,
            "position": 175,
            "domains": {"PF00870": [81]},
            "limit": 1,
            "offset": 0,
        },
    )
    assert data["success"] is True
    meta = data["meta_domains"]["PF00870"]
    assert len(meta["normal_variants"]) == 1
    block = meta["pagination"]["normal_variants"]
    assert block["limit"] == 1
    assert block["total"] == 2
    assert block["returned"] == 1
    assert block["truncated"] is True
