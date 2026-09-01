"""Tests that ready MetaDome poll results remain bound to the requested id."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from metadome_link.exceptions import UpstreamSchemaError

TID = "ENST00000269305.9"
FX = pathlib.Path(__file__).parent / "fixtures" / "metadome"


def _load_result() -> dict[str, Any]:
    """Load a complete valid landscape and alter only its identity."""
    result = json.loads((FX / "result_TP53.json").read_text())
    result["transcript_id"] = "ENST00000504937.5"
    return result


async def test_get_landscape_poll_result_must_match_requested_transcript(
    metadome_service: Any,
) -> None:
    """A cache-miss poll cannot return or cache another transcript's result."""
    wrong = _load_result()

    async def wrong_result(
        _transcript_id: str, *, soft_deadline_s: float
    ) -> tuple[str, dict[str, Any]]:
        return "ready", wrong

    metadome_service._client.poll_until_ready = wrong_result  # type: ignore[method-assign]
    with pytest.raises(UpstreamSchemaError) as exc_info:
        await metadome_service.get_landscape(TID, limit=5, offset=0, response_mode="compact")
    assert exc_info.value.extra["field"] == "transcript_id"
    assert metadome_service.cache.get_result(TID) is None
