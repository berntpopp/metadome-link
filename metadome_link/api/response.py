"""Total decoding helpers for MetaDome HTTP responses."""

from __future__ import annotations

from typing import Any

import httpx

from metadome_link.exceptions import UpstreamSchemaError


def parse_json(response: httpx.Response) -> Any:
    """Decode JSON and classify malformed or excessively deep payloads."""
    try:
        return response.json()
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UpstreamSchemaError(
            "MetaDome returned malformed JSON.", field="response_body"
        ) from exc
