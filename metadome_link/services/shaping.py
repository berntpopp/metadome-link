"""Response-mode projection for MetaDome payloads.

``standard`` / ``full`` are the identity (the complete record, unmodified).
``compact`` (the default) drops null/empty values — ``None``, ``[]``, ``""``,
``{}`` — to keep token counts low.  ``minimal`` keeps the mandatory envelope and
every ESSENTIAL field — identity anchors, scalar results, collections, and the
mandatory ``recommended_citation`` — dropping only verbose/redundant prose (the
data-currency caveat, already carried in ``_meta``). A verbosity mode narrows a
payload; it must never empty a result, of any shape.

``char_budget_guard`` provides a last-resort token-budget safety valve: when
the serialised payload exceeds ``max_chars``, it iteratively truncates list
fields (longest first -- top-level lists like ``positional_annotation`` /
``positions`` / ``regions`` AND lists nested one level under a dict, such as
``meta_domains.<PF>.pathogenic_variants``) until the budget is met, then injects
a ``dropped_summary`` field describing what was removed.
"""

from __future__ import annotations

import copy
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

#: The ONLY record fields ``minimal`` may drop: verbose/redundant PROSE that
#: duplicates provenance already carried in every ``_meta`` (``data_versions`` +
#: ``unsafe_for_clinical_use``). Everything else in a record -- identity anchors,
#: scalar RESULTS (``sw_dn_ds``, ``ref_aa``, ``protein_pos``, ``job_id``,
#: ``status``, ``poll_after_s`` ...), collections, and the mandatory
#: ``recommended_citation`` -- is ESSENTIAL and survives ``minimal``. This is a
#: DENYLIST of prose, not an allowlist of results, so a scalar-result tool keeps
#: its scalars automatically (Response-Envelope v1: ``minimal`` narrows verbosity,
#: it must never empty a result).
_MINIMAL_DROP_PROSE: frozenset[str] = frozenset({"data_currency_caveat"})

#: Identity/grounding anchors a sparse fieldset always retains.
_FIELD_ANCHORS: frozenset[str] = frozenset(
    {"transcript_id", "gene_name", "protein_ac", "_meta", "success"}
)


def _is_empty(value: Any) -> bool:
    """True for the null/empty values compact mode drops."""
    return value is None or value == [] or value == "" or value == {}


def shape_record(record: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a MetaDome record to the requested verbosity.

    - ``minimal``: keep the mandatory envelope + identifiers and every ESSENTIAL
      result -- identity anchors, scalar results, collections, and the mandatory
      ``recommended_citation`` -- dropping only verbose/redundant prose
      (:data:`_MINIMAL_DROP_PROSE`, already carried in ``_meta``) and null/empty
      values. It MUST NOT empty a result of any shape (scalar OR collection);
      Response-Envelope v1, enforced by the behaviour gate.
    - ``compact``: drop null/empty values (``None``, ``[]``, ``""``, ``{}``) ;
      system keys (``_meta``, ``success``) are always preserved.
    - ``standard`` / ``full``: the complete record, unmodified.
    """
    if mode == "minimal":
        return {
            key: value
            for key, value in record.items()
            if key in _PRESERVE_KEYS or (key not in _MINIMAL_DROP_PROSE and not _is_empty(value))
        }
    if mode in ("standard", "full"):
        return dict(record)
    # compact
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key not in _PRESERVE_KEYS and _is_empty(value):
            continue
        out[key] = value
    return out


def select_fields(payload: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
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


#: Truncation step size: drop a chunk of items per pass so a large over-budget
#: payload converges in O(items / step) serialisations instead of one-by-one.
_GUARD_TRUNCATE_STEP = 8

#: A located, truncatable list: ``(dotted_label, owning_container, key)``. The
#: container is held by reference so a slice can be written straight back.
_ListTarget = tuple[str, dict[str, Any], str]


def _guard_list_targets(node: dict[str, Any], prefix: str = "") -> list[_ListTarget]:
    """Collect every non-empty list in *node*, recursing through dict scaffolding.

    Finds top-level list fields (e.g. ``positional_annotation``, ``positions``,
    ``regions``) AND lists nested under dict-valued fields at any depth (e.g.
    ``meta_domains.<PF>.pathogenic_variants``), which is where the bulk of a
    meta-domain payload lives. Empty lists and the injected ``dropped_summary``
    are skipped; only dicts are descended into (list items are never split).
    """
    targets: list[_ListTarget] = []
    for key, value in node.items():
        if key == "dropped_summary":
            continue
        label = f"{prefix}{key}"
        if isinstance(value, list) and value:
            targets.append((label, node, key))
        elif isinstance(value, dict):
            targets.extend(_guard_list_targets(value, prefix=f"{label}."))
    return targets


def char_budget_guard(payload: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    """Truncate list fields until the serialised payload fits within *max_chars*.

    When over budget the function iteratively removes items from the longest
    list field -- top-level OR nested under dict scaffolding at any depth (e.g.
    ``meta_domains.<PF>.pathogenic_variants``) -- until the budget is satisfied,
    then injects a ``dropped_summary`` field describing how many items were
    removed from which fields. Scalars, strings and dict scaffolding are never
    dropped -- only list *items* are removed.

    The budget is measured against ``len(json.dumps(payload))``.  If the
    payload is already within budget it is returned unchanged (no copy).
    """
    if len(json.dumps(payload)) <= max_chars:
        return payload

    result: dict[str, Any] = copy.deepcopy(payload)
    dropped: dict[str, int] = {}

    while len(json.dumps(result)) > max_chars:
        targets = _guard_list_targets(result)
        if not targets:
            raise ValueError("Response exceeds maximum size after list truncation.")
        label, container, key = max(targets, key=lambda t: len(t[1][t[2]]))
        lst = container[key]
        step = min(_GUARD_TRUNCATE_STEP, len(lst))
        container[key] = lst[: len(lst) - step]
        dropped[label] = dropped.get(label, 0) + step

    if dropped:
        parts = [f"{k}: {n} item(s) dropped" for k, n in sorted(dropped.items())]
        result["dropped_summary"] = "Truncated to fit response budget. " + "; ".join(parts) + "."
        _reconcile_pagination(result)

    return result


def _reconcile_pagination(payload: dict[str, Any]) -> None:
    """Make pagination describe the list rows that survived response-budget shaping."""
    pagination = payload.get("pagination")
    if isinstance(pagination, dict):
        for key in ("positional_annotation", "positions"):
            _reconcile_page_block(payload.get(key), pagination)

    meta_domains = payload.get("meta_domains")
    if not isinstance(meta_domains, dict):
        return
    for meta_domain in meta_domains.values():
        if not isinstance(meta_domain, dict):
            continue
        nested_pagination = meta_domain.get("pagination")
        if not isinstance(nested_pagination, dict):
            continue
        for key in ("normal_variants", "pathogenic_variants"):
            block = nested_pagination.get(key)
            if isinstance(block, dict):
                _reconcile_page_block(meta_domain.get(key), block)


def _reconcile_page_block(items: object, block: dict[str, Any]) -> None:
    """Set a page block's returned/truncated/next_offset from its actual list."""
    if not isinstance(items, list):
        return
    total = block.get("total")
    offset = block.get("offset")
    if not isinstance(total, int) or not isinstance(offset, int):
        return
    returned = len(items)
    next_offset = offset + returned
    block["returned"] = returned
    block["truncated"] = next_offset < total
    block["next_offset"] = next_offset if next_offset < total else None
