"""Total decoding helpers for MetaDome HTTP responses."""

from __future__ import annotations

import json
from typing import Any

import httpx

from metadome_link.exceptions import UpstreamSchemaError


def _reject_constant(value: str) -> object:
    """Reject JSON extensions that are not valid RFC 8259 values."""
    raise ValueError(f"nonstandard JSON constant: {value}")


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate object members instead of applying last-key-wins."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object member")
        result[key] = value
    return result


def _validate_unicode(value: object) -> None:
    """Reject lone UTF-16 surrogate code points in keys and values."""
    if isinstance(value, str):
        index = 0
        while index < len(value):
            code_point = ord(value[index])
            if 0xD800 <= code_point <= 0xDBFF:
                if index + 1 >= len(value) or not 0xDC00 <= ord(value[index + 1]) <= 0xDFFF:
                    raise ValueError("invalid Unicode scalar value")
                index += 2
            elif 0xDC00 <= code_point <= 0xDFFF:
                raise ValueError("invalid Unicode scalar value")
            else:
                index += 1
    elif isinstance(value, list):
        for item in value:
            _validate_unicode(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_unicode(key)
            _validate_unicode(item)


def parse_json_text(payload: str | bytes, *, field: str = "response_body") -> Any:
    """Decode text with the same strict JSON rules used for HTTP responses."""
    try:
        decoded = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_constant,
        )
        _validate_unicode(decoded)
        return decoded
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UpstreamSchemaError("MetaDome returned malformed JSON.", field=field) from exc


def parse_json(response: httpx.Response) -> Any:
    """Decode JSON and classify malformed or excessively deep payloads."""
    try:
        decoded = response.json(
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_constant,
        )
        _validate_unicode(decoded)
        return decoded
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UpstreamSchemaError(
            "MetaDome returned malformed JSON.", field="response_body"
        ) from exc
