"""Guard: metadome-link exposes no externally sourced free-text field (v1.1 no-untrusted-text).

metadome-link wraps the MetaDome web API (Wiel et al. 2019), which serves
per-residue missense tolerance scores (``sw_dn_ds``), Pfam domain
identifiers/coordinates, gnomAD/ClinVar per-position variant counts, and
transcript/protein identifiers. There is no upstream author-written prose
(no submission comments, disease descriptions, publication abstracts, or
curator narrative) anywhere in the response shape — only numeric scores,
positions, curated IDs/labels, and enums. This is a defense-in-depth
regression guard (Response-Envelope Standard v1.1, Task C): it does NOT
introduce a fence, envelope, or version bump, because there is nothing to
fence.

Two independent surfaces are checked so a future change cannot silently
introduce a prose field through either door:

1. Every declared MCP ``output_schema`` in :mod:`metadome_link.mcp.schemas`
   (walked recursively through nested ``properties``/``items``, since some
   sub-objects like the Pfam domain entry are one level down under a list).
2. Every raw upstream field name normalized in :mod:`metadome_link.api.models`
   (the ``TypedDict`` shapes the API client produces from the MetaDome
   response) — schemas.py declares its object properties permissively
   (``additionalProperties: true``, mirroring mondo-link) so a field can flow
   through to a tool's output without being named in the schema; checking the
   TypedDicts too closes that gap.

Both surfaces are asserted disjoint from ``FORBIDDEN_FREETEXT_KEYS``. If a
future change adds a field named e.g. ``description`` or ``notes`` to any
schema or upstream shape, this test fails loudly.
"""

from __future__ import annotations

from typing import Any, get_type_hints

from metadome_link.api import models as _models
from metadome_link.mcp import schemas as _schemas

# Curated nomenclature, numeric tolerance scores, positions, and stable IDs —
# no upstream prose surface. Matches the fleet-wide Task C forbidden-key set.
FORBIDDEN_FREETEXT_KEYS = {
    "definition",
    "description",
    "summary",
    "abstract",
    "notes",
    "comment",
    "involvement",
    "match",
    "phenotypes",
    "evidence",
    "criterion_description",
}


def _collect_property_keys(node: Any, keys: set[str]) -> None:
    """Recursively collect every JSON-schema ``properties`` key under ``node``."""
    if not isinstance(node, dict):
        return
    props = node.get("properties")
    if isinstance(props, dict):
        for key, sub_schema in props.items():
            keys.add(key)
            _collect_property_keys(sub_schema, keys)
    items = node.get("items")
    if isinstance(items, dict):
        _collect_property_keys(items, keys)


def _all_schema_constants() -> dict[str, dict[str, Any]]:
    """Every ``*_SCHEMA`` dict constant exported by ``metadome_link.mcp.schemas``.

    Introspected by name rather than hand-enumerated so a schema added for a
    future tool is automatically covered by this guard.
    """
    return {
        name: value
        for name, value in vars(_schemas).items()
        if name.endswith("_SCHEMA") and isinstance(value, dict)
    }


# ── 1. Declared MCP output schemas (recursive) ─────────────────────────────


def test_every_output_schema_has_no_free_text_surface() -> None:
    """No declared tool ``output_schema`` names a forbidden free-text key, at any depth."""
    schema_constants = _all_schema_constants()
    assert schema_constants, "expected at least one *_SCHEMA constant in metadome_link.mcp.schemas"

    for schema_name, schema in schema_constants.items():
        keys: set[str] = set()
        _collect_property_keys(schema, keys)
        offenders = keys & FORBIDDEN_FREETEXT_KEYS
        assert not offenders, (
            f"metadome introduced an unclassified free-text field in {schema_name}: {offenders}"
        )


def test_output_schema_enumeration_covers_all_eleven_tools() -> None:
    """Sanity check: the schema module still declares one schema per registered tool.

    metadome-link's own AGENTS.md invariant #7 pins the tool count at 11
    (``capabilities.TOOLS``); this guard's completeness depends on that count
    not silently drifting without a matching ``*_SCHEMA`` constant appearing.
    """
    from metadome_link.mcp.capabilities import TOOLS

    assert len(TOOLS) == 11
    schema_constants = _all_schema_constants()
    # get_diagnostics + get_server_capabilities + resolve_transcript + the 8
    # data tools == 11 tool schemas (one *_SCHEMA per tool, checked by name
    # convention rather than value equality since a couple of tool names
    # collapse to shared schema constants is NOT the case here — each tool has
    # its own schema).
    assert len(schema_constants) >= len(TOOLS)


# ── 2. Raw upstream shapes normalized in api/models.py ─────────────────────


def test_upstream_typed_shapes_have_no_free_text_surface() -> None:
    """No field normalized from the raw MetaDome API response is upstream prose.

    ``schemas.py`` declares its object properties permissively
    (``additionalProperties: true``), so a field could reach a tool's output
    without being named there. This checks the actual upstream-derived field
    names instead: ``TranscriptSummary``, ``Domain`` (Pfam entry — carries the
    short curated Pfam label ``Name``, e.g. "P53 DNA-binding domain", not
    open-ended prose), and ``LandscapePosition``.
    """
    typed_dicts = (_models.TranscriptSummary, _models.Domain, _models.LandscapePosition)
    for typed_dict in typed_dicts:
        field_names = {name.lower() for name in get_type_hints(typed_dict)}
        offenders = field_names & FORBIDDEN_FREETEXT_KEYS
        assert not offenders, (
            f"metadome introduced an unclassified free-text field in "
            f"{typed_dict.__name__}: {offenders}"
        )
