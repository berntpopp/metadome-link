"""Build-specific provenance must reach all discovery, envelope, and service paths."""

from __future__ import annotations

from metadome_link.api.client import MetaDomeClient
from metadome_link.cache.store import ResultCache
from metadome_link.config import ServerSettings
from metadome_link.mcp.capabilities import build_capabilities
from metadome_link.mcp.envelope import run_mcp_tool
from metadome_link.mcp.notfound_guard import unknown_tool_envelope
from metadome_link.mcp.service_adapters import set_metadome_service
from metadome_link.services.metadome_service import MetaDomeService

TID = "ENST00000269305.9"


async def test_alternate_profile_flows_into_capabilities_and_envelope(tmp_path: object) -> None:
    """A GRCh37 runtime cannot advertise the default GRCh38 provenance."""
    settings = ServerSettings(metadome={"genome_build": "GRCh37.p13"})
    client = MetaDomeClient(settings)
    cache = ResultCache(db_path=str(tmp_path) + "/cache.sqlite", data_version=client.data_version)
    service = MetaDomeService(client, cache, settings=settings)
    set_metadome_service(service)
    try:
        caps = build_capabilities()
        assert caps["genome_build"] == "GRCh37.p13"
        assert caps["data_versions"]["assembly"] == "GRCh37.p13"

        async def plain_payload() -> dict[str, object]:
            return {"answer": "ok"}

        result = await run_mcp_tool("probe", plain_payload)
        assert result["_meta"]["data_versions"]["assembly"] == "GRCh37.p13"
        cache.put_result(
            TID,
            {
                "transcript_id": TID,
                "positional_annotation": [
                    {
                        "cdna_pos": "c.1-3",
                        "chr": "chr17",
                        "chr_positions": "g.1-3",
                        "domains": {},
                        "protein_pos": 1,
                        "ref_aa": "M",
                        "ref_aa_triplet": "Met",
                        "ref_codon": "ATG",
                        "strand": "-",
                        "sw_coverage": 0.5,
                        "sw_dn_ds": 0.4,
                        "sw_size": 10,
                    }
                ],
            },
        )
        comparison = await service.compare_positions(TID, [1], response_mode="compact")
        assert "GRCh37.p13" in comparison["data_currency_caveat"]
        assert "2018-06-03" not in comparison["data_currency_caveat"]
        assert unknown_tool_envelope()["_meta"]["data_versions"]["assembly"] == "GRCh37.p13"
    finally:
        set_metadome_service(None)
        cache.close()
        await client.aclose()
