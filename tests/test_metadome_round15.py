"""Adversarial acceptance tests for the final MetaDome review round."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from metadome_link.mcp import schemas
from metadome_link.services.metadome_service import MetaDomeService

_NUMERIC_USER = re.compile(r"^[1-9][0-9]*:[1-9][0-9]*$")


class _TagTolerantLoader(yaml.SafeLoader):
    """A SafeLoader that tolerates the `!reset` / `!override` Compose merge tags.

    `docker-compose.prod.yml` (one of the release-manifest files below) uses these
    custom tags to reset/override list fields across `-f` overlays; plain
    `yaml.safe_load` raises on an unknown tag.
    """


_TagTolerantLoader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None
    ),
)

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


def test_npm_overlay_declares_a_numeric_non_root_user() -> None:
    """The deployed overlay declares this image's own numeric uid:gid.

    The fleet controller (strato_v6_docker_npm,
    scripts/utils/deployment_preflight.py) accepts a declared `user` only as
    numeric non-root, and its runtime observer proves the effective uid from
    /proc against it -- a name like `app` inspects as the string "app" and is
    rejected.
    """
    root = Path(__file__).parents[1]
    text = (root / "docker/docker-compose.npm.yml").read_text(encoding="utf-8")
    # _TagTolerantLoader extends SafeLoader; its multi_constructor only ever returns
    # a scalar string or None, so it cannot instantiate arbitrary objects.
    compose = yaml.load(text, Loader=_TagTolerantLoader)  # noqa: S506
    for name, service in compose["services"].items():
        user = service.get("user")
        assert isinstance(user, str) and _NUMERIC_USER.fullmatch(user), (
            f"{name} declares user={user!r}; the deploy contract requires a "
            "numeric uid:gid matching this image's own docker/Dockerfile account"
        )


def test_release_compose_files_never_declare_a_user() -> None:
    """The release gate forbids what the deploy overlay requires.

    `container_release.py validate-compose` rejects a rendered application
    service that declares `user` on any Compose file listed in
    `container-release.json` -- `user` is not in its `ALLOWED_SERVICE_KEYS`. The
    numeric user therefore belongs only in `docker-compose.npm.yml`, never here.
    """
    root = Path(__file__).parents[1]
    manifest = json.loads((root / "container-release.json").read_text(encoding="utf-8"))
    for rel_path in manifest["service"]["compose_files"]:
        text = (root / rel_path).read_text(encoding="utf-8")
        compose = yaml.load(text, Loader=_TagTolerantLoader)  # noqa: S506
        for name, service in (compose.get("services") or {}).items():
            assert "user" not in service, (
                f"{rel_path} service {name!r} declares 'user'; the release gate's "
                "ALLOWED_SERVICE_KEYS forbids it here"
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
