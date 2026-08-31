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
    MAX_PROTEIN_POSITION,
)
from metadome_link.exceptions import InvalidInputError
from metadome_link.services.landscape import position_to_entry


def validate_meta_domain_selector(
    landscape: dict[str, Any], position: int, domains: object
) -> dict[str, list[int]]:
    """Validate an explicit selector against one residue's advertised domains."""
    requested = validate_meta_domain_request(position, domains)
    entry = position_to_entry(landscape, position)
    available = entry.get("domains")
    available_map = available if isinstance(available, dict) else {}
    total_positions = 0
    validated: dict[str, list[int]] = {}
    for pfam_id, positions in requested.items():
        if (
            type(pfam_id) is not str
            or not pfam_id
            or len(pfam_id) > MAX_META_DOMAIN_SELECTOR_KEY_CHARS
        ):
            raise InvalidInputError("domains contains an invalid Pfam id.", field="domains")
        mapping = available_map.get(pfam_id)
        consensus = mapping.get("consensus_pos") if isinstance(mapping, dict) else None
        if not isinstance(consensus, list):
            raise InvalidInputError("domains contains an unknown Pfam id.", field="domains")
        checked: list[int] = []
        for consensus_pos in positions:
            if consensus_pos not in consensus:
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


def validate_meta_domain_request(position: object, domains: object) -> dict[str, list[int]]:
    """Validate endpoint-6 request shape before any upstream network call."""
    if type(position) is not int or not 1 <= position <= MAX_PROTEIN_POSITION:
        raise InvalidInputError("Position must be a bounded positive integer.", field="position")
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
    checked: dict[str, list[int]] = {}
    total = 0
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
        values: list[int] = []
        for value in positions:
            if type(value) is not int or not 1 <= value <= MAX_GENOMIC_POSITION or value in values:
                raise InvalidInputError(
                    "domains contains an invalid consensus position.", field="domains"
                )
            values.append(value)
        total += len(values)
        if total > MAX_META_DOMAIN_SELECTOR_POSITIONS:
            raise InvalidInputError(
                "The domain selector contains too many positions.", field="domains"
            )
        checked[pfam_id] = values
    return checked


def require_complete_range(start: int | None, stop: int | None) -> None:
    """Reject a one-sided inclusive range before any landscape lookup."""
    if (start is None) != (stop is None):
        raise InvalidInputError(
            "position_start and position_stop must be supplied together.",
            field="position_start/position_stop",
        )
    if start is not None and (
        type(start) is not int
        or type(stop) is not int
        or not 1 <= start <= MAX_PROTEIN_POSITION
        or not 1 <= stop <= MAX_PROTEIN_POSITION
        or start > stop
    ):
        raise InvalidInputError(
            "position_start and position_stop must be bounded, ordered integers.",
            field="position_start/position_stop",
        )


def require_position_xor(position: object, start: object, stop: object) -> None:
    """Reject ambiguous single-position/range selectors at service boundaries."""
    if position is not None and (start is not None or stop is not None):
        raise InvalidInputError(
            "position cannot be combined with position_start/position_stop.", field="position"
        )
    require_complete_range(start, stop)  # type: ignore[arg-type]
