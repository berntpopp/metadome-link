"""Small helpers shared by the output-schema fragments."""

from __future__ import annotations

import json
import re
from typing import Any


def closed(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a compact closed object schema with an explicit required set."""
    groups: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for name, value in properties.items():
        identity = json.dumps(value, sort_keys=True, separators=(",", ":"))
        groups.setdefault(identity, (value, []))[1].append(name)
    patterns = {}
    for value, names in groups.values():
        joined = "|".join(re.escape(name) for name in names)
        patterns[f"^{joined}$" if len(names) == 1 else f"^({joined})$"] = value
    schema: dict[str, Any] = {
        "type": "object",
        "patternProperties": patterns,
        "additionalProperties": False,
    }
    if required and set(required) == set(properties):
        schema["minProperties"] = len(required)
    elif required:
        schema["required"] = list(required)
    property_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if "minProperties" in schema:
        property_schema["minProperties"] = schema["minProperties"]
    if "required" in schema:
        property_schema["required"] = schema["required"]
    return min(
        (schema, property_schema),
        key=lambda value: len(json.dumps(value, separators=(",", ":"))),
    )
