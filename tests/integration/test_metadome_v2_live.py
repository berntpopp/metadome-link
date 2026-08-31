"""Opt-in live integration contract for MetaDome v2 build-scoped endpoints.

Set ``METADOME_LINK_LIVE_INTEGRATION=1`` to run against the configured public
service. These tests deliberately use no captured response fixtures: a configured
run is evidence from the live API, while the default test run is an explicit skip.
"""

from __future__ import annotations

import os

import pytest

from metadome_link.api.client import MetaDomeClient
from metadome_link.config import MetaDomeSettings, ServerSettings

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("METADOME_LINK_LIVE_INTEGRATION") != "1",
    reason="set METADOME_LINK_LIVE_INTEGRATION=1 for live MetaDome evidence",
)
async def test_six_build_scoped_v2_endpoints() -> None:
    """Exercise transcripts, submit, status, result, error and meta-domain live."""
    base_url = os.environ.get(
        "METADOME_LINK_LIVE_BASE_URL", "https://www.metadome.app/metadome/api"
    )
    transcript_id = os.environ.get("METADOME_LINK_LIVE_TRANSCRIPT_ID")
    gene = os.environ.get("METADOME_LINK_LIVE_GENE")
    if not transcript_id or not gene:
        pytest.skip("set METADOME_LINK_LIVE_GENE and METADOME_LINK_LIVE_TRANSCRIPT_ID")
    settings = ServerSettings(
        metadome=MetaDomeSettings(base_url=base_url),
        _env_file=None,
    )
    client = MetaDomeClient(settings)
    try:
        transcripts = await client.get_transcripts(gene)
        assert transcripts and any(row["gencode_id"] == transcript_id for row in transcripts)
        assert await client.submit_visualization(transcript_id) == transcript_id
        status, result = await client.poll_until_ready(transcript_id, soft_deadline_s=300)
        assert status in {"ready", "processing", "failed"}
        if status == "processing":
            pytest.fail("live MetaDome build remained pending beyond the bounded deadline")
        if status == "failed":
            error = await client.get_error(transcript_id)
            pytest.fail(f"live MetaDome build failed: {type(error).__name__}")
        assert result is not None and result["transcript_id"] == transcript_id
        error = await client.get_error(transcript_id)
        assert isinstance(error, dict)
        selector: tuple[int, dict[str, list[int]]] | None = None
        for entry in result.get("positional_annotation", []):
            if not isinstance(entry, dict) or type(entry.get("protein_pos")) is not int:
                continue
            domains = entry.get("domains")
            if not isinstance(domains, dict):
                continue
            request: dict[str, list[int]] = {}
            for domain, mapping in domains.items():
                if isinstance(mapping, dict) and isinstance(mapping.get("consensus_pos"), list):
                    values = [p for p in mapping["consensus_pos"] if type(p) is int]
                    if values:
                        request[domain] = values[:1]
            if request:
                selector = (entry["protein_pos"], request)
                break
        assert selector is not None, "live result exposed no usable meta-domain selector"
        annotation = await client.get_metadomain_annotation(transcript_id, *selector)
        assert isinstance(annotation, dict) and set(annotation) == set(selector[1])
    finally:
        await client.aclose()
