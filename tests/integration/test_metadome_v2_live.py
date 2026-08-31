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
    transcript_id = os.environ.get("METADOME_LINK_LIVE_TRANSCRIPT_ID", "ENST00000269305.9")
    gene = os.environ.get("METADOME_LINK_LIVE_GENE", "TP53")
    settings = ServerSettings(
        metadome=MetaDomeSettings(base_url=base_url),
        _env_file=None,
    )
    client = MetaDomeClient(settings)
    try:
        transcripts = await client.get_transcripts(gene)
        assert transcripts and any(row["gencode_id"] == transcript_id for row in transcripts)
        assert await client.submit_visualization(transcript_id) == transcript_id
        status = await client.get_status(transcript_id)
        assert status in {"PENDING", "SENT", "STARTED", "RECEIVED", "RETRY", "SUCCESS", "FAILURE"}
        if status == "SUCCESS":
            result = await client.get_result(transcript_id)
            assert result["transcript_id"] == transcript_id
        error = await client.get_error(transcript_id)
        assert isinstance(error, dict)
        annotation = await client.get_metadomain_annotation(transcript_id, 175, {"PF00870": [81]})
        assert isinstance(annotation, dict) and "PF00870" in annotation
    finally:
        await client.aclose()
