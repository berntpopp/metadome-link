"""Closed JSON-Schema contracts for executable ``_meta.next_commands``."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from metadome_link.mcp.schema_utils import closed

_STR = {"type": "string"}


def _argument_names_schema(argument_names: Iterable[str]) -> dict[str, Any]:
    """Return a compact exact allowlist for command argument property names."""
    names = list(argument_names)
    if len(names) == 1:
        return {"const": names[0]}

    parts = [re.escape(name) for name in names]
    position_names = {"position", "positions", "position_start", "position_stop"}
    present = position_names.intersection(names)
    replacement: str | None = None
    if present == position_names:
        replacement = "position(s|_start|_stop)?"
    elif present == {"position", "position_start", "position_stop"}:
        replacement = "position(_start|_stop)?"
    elif present == {"position", "positions"}:
        replacement = "positions?"
    if replacement is not None:
        first = min(names.index(name) for name in present)
        parts = [part for name, part in zip(names, parts, strict=True) if name not in present]
        parts.insert(first, replacement)
    return {"pattern": f"^({'|'.join(parts)})$"}


def command_schema(argument_names: Iterable[str], *, domains: bool = False) -> dict[str, Any]:
    """Build a closed command schema for one output's actual follow-up fields."""
    names = tuple(argument_names)
    args_schema: dict[str, Any] = {
        "type": "object",
        "propertyNames": _argument_names_schema(names),
    }
    if domains:
        args_schema["properties"] = {
            "domains": {
                "type": "object",
                "additionalProperties": {"type": "array", "items": {"type": "integer"}},
            }
        }
    return closed({"tool": _STR, "arguments": args_schema}, ("tool", "arguments"))


# The direct contract accepts every legitimate argument shape. Individual
# output schemas use narrower constants to keep the public surface compact.
NEXT_COMMAND = command_schema(
    (
        "query",
        "transcript_id",
        "position",
        "positions",
        "position_start",
        "position_stop",
        "source",
        "limit",
        "offset",
        "domains",
    ),
    domains=True,
)

CAPABILITIES_NEXT_COMMAND = command_schema(("query",))
DIAGNOSTICS_NEXT_COMMAND = command_schema(("query",))
RESOLVE_NEXT_COMMAND = command_schema(("query", "transcript_id"))
REQUEST_NEXT_COMMAND = command_schema(("transcript_id",))
LANDSCAPE_NEXT_COMMAND = command_schema(
    ("transcript_id", "position", "position_start", "position_stop", "limit", "offset")
)
POSITION_NEXT_COMMAND = command_schema(("transcript_id", "position", "positions"))
VARIANT_NEXT_COMMAND = command_schema(
    ("transcript_id", "position", "position_start", "position_stop", "source", "limit", "offset")
)
COMPARE_NEXT_COMMAND = command_schema(("transcript_id", "position"))
DOMAINS_NEXT_COMMAND = command_schema(
    ("transcript_id", "position", "limit", "offset", "domains"), domains=True
)
META_NEXT_COMMAND = command_schema(
    ("transcript_id", "position", "limit", "offset", "domains"), domains=True
)
SUMMARY_NEXT_COMMAND = command_schema(("transcript_id", "position"))
