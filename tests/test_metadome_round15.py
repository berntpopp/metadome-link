"""Adversarial acceptance tests for the final MetaDome review round."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from metadome_link.mcp import schemas
from metadome_link.services.metadome_service import MetaDomeService

_SCHEMAS = [value for name, value in vars(schemas).items() if name.endswith("_SCHEMA")]


def test_output_schemas_are_discriminated_and_closed() -> None:
    """A bare success flag or unknown nested state cannot advertise a valid result."""
    for schema in _SCHEMAS:
        for bare in ({"success": True}, {"success": False}):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(bare, schema)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {
                    "success": True,
                    "_meta": {
                        "tool": "x",
                        "request_id": "r",
                        "data_versions": {},
                        "unsafe_for_clinical_use": True,
                        "unexpected": True,
                    },
                },
                schema,
            )


def test_schema_arrays_and_nested_records_have_typed_items() -> None:
    """Advertised arrays must reject arbitrary records and scalar values."""
    for schema in _SCHEMAS:
        encoded = json.dumps(schema)
        assert '"items"' in encoded
    for schema in _SCHEMAS:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {
                    "success": True,
                    "_meta": {
                        "tool": "x",
                        "request_id": "r",
                        "data_versions": {},
                        "unsafe_for_clinical_use": True,
                    },
                    "domains": ["not-a-domain"],
                },
                schema,
            )


def test_data_volume_is_canonical_and_non_root() -> None:
    """Every shipped Docker surface agrees on the writable /data volume."""
    root = Path(__file__).parents[1]
    candidates = [
        root / ".env.example",
        root / ".env.docker.example",
        root / "docker/Dockerfile",
        root / "docker/docker-compose.yml",
        root / "docker/docker-compose.prod.yml",
        root / "docker/docker-compose.npm.yml",
        root / "docker/README.md",
        root / "docs/deployment.md",
        root / "README.md",
    ]
    for path in candidates:
        text = path.read_text()
        assert "/app/data" not in text, path
    assert (
        "METADOME_LINK_CACHE__DB_PATH=/data/metadome_cache.sqlite"
        in (root / ".env.docker.example").read_text()
    )


def test_processing_service_payload_has_no_wire_success() -> None:
    """The data plane returns payload state only; MCP owns success/envelopes."""
    source = Path(__file__).parents[1] / "metadome_link/services/metadome_service.py"
    text = source.read_text()
    assert '"success": True' not in text


def test_capabilities_aggregate_is_not_claimed_read_only() -> None:
    from metadome_link.mcp.capabilities import build_capabilities

    assert build_capabilities()["read_only"] is False


def test_cache_cli_uses_configured_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
) -> None:
    from metadome_link.cache import store
    from metadome_link.config import ServerSettings

    monkeypatch.setattr(
        store,
        "settings",
        ServerSettings(
            metadome={"genome_build": "GRCh37.p13"},
            cache={"db_path": str(tmp_path / "cache.sqlite")},
            _env_file=None,
        ),
    )
    store.status()
    assert "grch37.p13" in capsys.readouterr().out.lower()


def test_diagnostics_schema_does_not_claim_unprobed_health() -> None:
    encoded = json.dumps(schemas.GET_DIAGNOSTICS_SCHEMA)
    assert "data_available" not in encoded
    assert "upstream_reachable" not in encoded


def test_provenance_args_are_propagated_by_build_workflows() -> None:
    root = Path(__file__).parents[1]
    makefile = (root / "Makefile").read_text()
    assert "BUILD_DATE" in makefile and "VCS_REF" in makefile
    for workflow in (root / ".github/workflows").glob("*.yml"):
        text = workflow.read_text()
        if "docker build" in text:
            assert "VCS_REF" in text or "build-args" in text


@pytest.mark.asyncio
async def test_out_of_protein_ranges_are_named_errors(metadome_service: MetaDomeService) -> None:
    """A range beyond the actual landscape cannot silently become an empty page."""
    with pytest.raises(Exception, match="position_stop"):
        await metadome_service.get_landscape(
            "ENST00000269305.9",
            position_start=1,
            position_stop=10000,
            limit=10,
            offset=0,
            response_mode="standard",
        )
    with pytest.raises(Exception, match="position_stop"):
        await metadome_service.get_variant_counts(
            "ENST00000269305.9",
            position_start=1,
            position_stop=10000,
            response_mode="standard",
        )
