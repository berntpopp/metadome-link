"""Finite, residue-bound validation for caller-supplied endpoint-6 selectors."""

from __future__ import annotations

import json
from typing import Any

from metadome_link.constants import (
    MAX_GENOMIC_POSITION,
    MAX_META_DOMAIN_SELECTOR_DOMAINS,
    MAX_META_DOMAIN_SELECTOR_KEY_CHARS,
    MAX_META_DOMAIN_SELECTOR_POSITIONS,
    MAX_META_DOMAIN_SELECTOR_POSITIONS_PER_DOMAIN,
    MAX_META_DOMAIN_SELECTOR_REQUEST_BYTES,
)
from metadome_link.exceptions import InvalidInputError
from metadome_link.services.landscape import position_to_entry


def validate_meta_domain_selector(
    landscape: dict[str, Any], position: int, domains: object
) -> dict[str, list[int]]:
    """Validate an explicit selector against one residue's advertised domains."""
    if type(position) is not int or position < 1:
        raise InvalidInputError("Position must be a positive integer.", field="position")
    entry = position_to_entry(landscape, position)
    if not isinstance(domains, dict):
        raise InvalidInputError("domains must be a map of Pfam ids to positions.", field="domains")
    if len(domains) > MAX_META_DOMAIN_SELECTOR_DOMAINS:
        raise InvalidInputError("Too many domain selectors.", field="domains")
    try:
        encoded = json.dumps(domains, separators=(",", ":"), ensure_ascii=False).encode()
    except (TypeError, ValueError, OverflowError):
        raise InvalidInputError(
            "domains must contain finite JSON values.", field="domains"
        ) from None
    if len(encoded) > MAX_META_DOMAIN_SELECTOR_REQUEST_BYTES:
        raise InvalidInputError("The domain selector request is too large.", field="domains")

    available = entry.get("domains")
    available_map = available if isinstance(available, dict) else {}
    total_positions = 0
    validated: dict[str, list[int]] = {}
    for pfam_id, positions in domains.items():
        if (
            type(pfam_id) is not str
            or not pfam_id
            or len(pfam_id) > MAX_META_DOMAIN_SELECTOR_KEY_CHARS
        ):
            raise InvalidInputError("domains contains an invalid Pfam id.", field="domains")
        if type(positions) is not list or not positions:
            raise InvalidInputError(
                "Each selected Pfam id needs a non-empty position list.", field="domains"
            )
        if len(positions) > MAX_META_DOMAIN_SELECTOR_POSITIONS_PER_DOMAIN:
            raise InvalidInputError(
                "A domain selector position list is too large.", field="domains"
            )
        mapping = available_map.get(pfam_id)
        consensus = mapping.get("consensus_pos") if isinstance(mapping, dict) else None
        if not isinstance(consensus, list):
            raise InvalidInputError("domains contains an unknown Pfam id.", field="domains")
        checked: list[int] = []
        for consensus_pos in positions:
            if (
                type(consensus_pos) is not int
                or consensus_pos < 1
                or consensus_pos > MAX_GENOMIC_POSITION
                or consensus_pos not in consensus
                or consensus_pos in checked
            ):
                raise InvalidInputError(
                    "domains contains an unknown consensus position.", field="domains"
                )
            checked.append(consensus_pos)
        total_positions += len(checked)
        if total_positions > MAX_META_DOMAIN_SELECTOR_POSITIONS:
            raise InvalidInputError(
                "The domain selector contains too many positions.", field="domains"
            )
        validated[pfam_id] = checked
    return validated


def require_complete_range(start: int | None, stop: int | None) -> None:
    """Reject a one-sided inclusive range before any landscape lookup."""
    if (start is None) != (stop is None):
        raise InvalidInputError(
            "position_start and position_stop must be supplied together.",
            field="position_start/position_stop",
        )
