"""Shared finite numeric predicates for upstream MetaDome response validation."""

from __future__ import annotations

import math

from metadome_link.constants import MAX_CLINVAR_ID, MAX_VARIANT_COUNT


def is_finite_number(value: object) -> bool:
    """Accept JSON numbers only when they are finite and not booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def is_valid_clinvar_id(value: object) -> bool:
    """Accept the numeric forms emitted by the two upstream v2 endpoints."""
    if isinstance(value, str):
        stripped = value.lstrip("0")
        return (
            bool(stripped)
            and all("0" <= c <= "9" for c in stripped)
            and (
                len(stripped) < len(str(MAX_CLINVAR_ID))
                or (len(stripped) == len(str(MAX_CLINVAR_ID)) and stripped <= str(MAX_CLINVAR_ID))
            )
        )
    return is_integer_at_least(value, 1, MAX_CLINVAR_ID)


def is_finite_integer(value: object) -> bool:
    """Accept an integer or integer-valued finite float, excluding booleans."""
    return is_finite_number(value) and (
        isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    )


def is_nonnegative_integer_number(value: object) -> bool:
    """Validate count values represented as JSON integers or integral floats."""
    return is_integer_at_least(value, 0, MAX_VARIANT_COUNT)


def is_integer_at_least(value: object, minimum: int, maximum: int | None = None) -> bool:
    """Check an integral finite numeric value against inclusive bounds."""
    return (
        is_finite_integer(value)
        and isinstance(value, (int, float))
        and value >= minimum
        and (maximum is None or value <= maximum)
    )
