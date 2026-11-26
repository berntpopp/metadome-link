"""Response-Envelope v1 §1: a successful data result carries its record under ``result``.

Every MetaDome data tool describes one transcript or position, so each returns a
single ``result`` object. Envelope keys, the citation and caveat, the budget note and
the list metadata (``pagination``) stay at the top level.
"""

from __future__ import annotations

from typing import Any

from metadome_link.provenance import OPS_TOOLS

#: Keys that stay beside ``result`` at the envelope top level.
TOP_LEVEL = frozenset(
    {"success", "_meta", "pagination", "recommended_citation", "data_currency_caveat"}
    | {"dropped_summary"}
)


def nest_payload(tool_name: str, result: dict[str, Any]) -> None:
    """Move a success payload under ``result`` in place; errors and ops tools stay flat."""
    if result.get("success") is not True or tool_name in OPS_TOOLS:
        return
    result["result"] = {k: result.pop(k) for k in list(result) if k not in TOP_LEVEL}
