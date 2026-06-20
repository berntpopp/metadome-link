"""Response-mode projection for MetaDome payloads.

``standard`` / ``full`` are the identity (the complete record, unmodified).
``compact`` (the default) drops null/empty values — ``None``, ``[]``, ``""``,
``{}`` — to keep token counts low.  ``minimal`` retains only the identity
anchors (``transcript_id`` + ``gene_name``) and a few system keys.

``char_budget_guard`` provides a last-resort token-budget safety valve: when
the serialised payload exceeds ``max_chars``, it iteratively truncates list
fields (longest first) until the budget is met, then injects a
``dropped_summary`` field describing what was removed.
"""

from __future__ import annotations

import json
from typing import Any

from metadome_link.constants import DEFAULT_RESPONSE_MODE, RESPONSE_MODES

# Re-export for upstream consumers who import these directly from this module.
__all__ = [
    "DEFAULT_RESPONSE_MODE",
    "RESPONSE_MODES",
    "char_budget_guard",
    "select_fields",
    "shape_record",
]

#: System-level keys that are always preserved (never dropped by compact/minimal).
_PRESERVE_KEYS: frozenset[str] = frozenset({"_meta", "success"})

#: Identity anchors kept in ``minimal`` mode.
_MINIMAL_KEEP: frozenset[str] = frozenset({"transcript_id", "gene_name", "_meta", "success"})

#: Identity/grounding anchors a sparse fieldset always retains.
_FIELD_ANCHORS: frozenset[str] = frozenset(
    {"transcript_id", "gene_name", "protein_ac", "_meta", "success"}
)


def _is_empty(value: Any) -> bool:
    """True for the null/empty values compact mode drops."""
    return value is None or value == [] or value == "" or value == {}


def shape_record(record: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a MetaDome record to the requested verbosity.

    - ``minimal``: ``transcript_id`` + ``gene_name`` (and system keys).
    - ``compact``: drop null/empty values (``None``, ``[]``, ``""``, ``{}``) ;
      system keys (``_meta``, ``success``) are always preserved.
    - ``standard`` / ``full``: the complete record, unmodified.
    """
    if mode == "minimal":
        return {k: v for k, v in record.items() if k in _MINIMAL_KEEP}
    if mode in ("standard", "full"):
        return dict(record)
    # compact
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key not in _PRESERVE_KEYS and _is_empty(value):
            continue
        out[key] = value
    return out


def select_fields(
    payload: dict[str, Any], fields: list[str] | None
) -> dict[str, Any]:
    """Project a payload to a caller-requested sparse fieldset.

    Identity/grounding anchors (``transcript_id``, ``gene_name``,
    ``protein_ac``, plus the preserved ``_meta``/``success``) are always
    retained.  Supports top-level keys and ONE level of dotting into a grouped
    object — e.g. ``"counts.gnomad"`` keeps only the ``gnomad`` sub-key under
    ``counts``.  Unknown fields are skipped (open-world).  Returns the payload
    unchanged when ``fields`` is falsy.
    """
    if not fields:
        return payload
    out: dict[str, Any] = {k: v for k, v in payload.items() if k in _FIELD_ANCHORS}
    for field in fields:
        top, _, sub = field.partition(".")
        if sub:
            container = payload.get(top)
            if isinstance(container, dict) and sub in container:
                nested = out.setdefault(top, {})
                if isinstance(nested, dict):
                    nested[sub] = container[sub]
        elif top in payload:
            out[top] = payload[top]
    return out


def char_budget_guard(
    payload: dict[str, Any], *, max_chars: int
) -> dict[str, Any]:
    """Truncate list fields until the serialised payload fits within *max_chars*.

    When over budget the function iteratively removes items from the longest
    list-valued field until the budget is satisfied, then injects a
    ``dropped_summary`` field describing how many items were removed from which
    fields.  Scalar fields (strings, numbers, dicts) are never truncated.

    The budget is measured against ``len(json.dumps(payload))``.  If the
    payload is already within budget it is returned unchanged (no copy).
    """
    if len(json.dumps(payload)) <= max_chars:
        return payload

    result: dict[str, Any] = dict(payload)
    dropped: dict[str, int] = {}

    while len(json.dumps(result)) > max_chars:
        # Find the list field with the most items (excluding dropped_summary itself)
        list_fields = [
            (k, v) for k, v in result.items() if isinstance(v, list) and k != "dropped_summary"
        ]
        if not list_fields:
            # Nothing more to truncate
            break
        # Pick the longest
        key, lst = max(list_fields, key=lambda kv: len(kv[1]))
        if len(lst) == 0:
            # All lists are empty, nothing to do
            break
        # Remove one item from the end
        result[key] = lst[:-1]
        dropped[key] = dropped.get(key, 0) + 1

    if dropped:
        parts = [f"{k}: {n} item(s) dropped" for k, n in sorted(dropped.items())]
        result["dropped_summary"] = "Truncated to fit response budget. " + "; ".join(parts) + "."

    return result
