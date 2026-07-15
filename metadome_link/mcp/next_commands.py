"""Builders for ``_meta.next_commands`` entries: ``{tool, arguments}`` steps.

The envelope-facing subset (``cmd``, ``widen_cmd``, ``page_cmd``,
``default_error_next_commands``) is consumed by the error boundary; the per-tool
``after_*`` chainers (added in later tasks) steer the success path
(resolve_transcript -> request_tolerance_landscape -> get_tolerance_landscape ->
positions / variants / domains / meta-domain / summarize).
"""

from __future__ import annotations

from typing import Any

from metadome_link.identifiers import looks_like_transcript_query


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def widen_cmd(tool: str, base_args: dict[str, Any], total: int, ceiling: int) -> dict[str, Any]:
    """A ready-to-call step that re-runs ``tool`` with ``limit`` raised to fit."""
    return cmd(tool, **{**base_args, "limit": min(total, ceiling)})


def page_cmd(tool: str, base_args: dict[str, Any], next_offset: int) -> dict[str, Any]:
    """A ready-to-call step that fetches the NEXT page (advance ``offset`` forward).

    Preferred over ``widen_cmd`` for large closures: it never re-sends rows the
    client already has, where raising ``limit`` re-fetches the whole head.
    """
    return cmd(tool, **{**base_args, "offset": next_offset})


def _more_steps(
    tool: str, base_args: dict[str, Any], payload: dict[str, Any], ceiling: int
) -> list[dict[str, Any]]:
    """Forward-page step (if any) then a widen step, for a truncated list payload."""
    if not payload.get("truncated"):
        return []
    steps: list[dict[str, Any]] = []
    next_offset = payload.get("next_offset")
    if next_offset is not None:
        steps.append(page_cmd(tool, base_args, int(next_offset)))
    steps.append(widen_cmd(tool, base_args, int(payload.get("total", 0)), ceiling))
    return steps


#: Tools whose first positional argument is a free-text gene/transcript query.
_QUERY_TOOLS = {"resolve_transcript"}

#: Tools keyed on a built transcript id (recovery routes through request+poll).
_LANDSCAPE_TOOLS = {
    "get_tolerance_landscape",
    "get_position_tolerance",
    "get_variant_counts",
    "compare_positions",
    "get_protein_domains",
    "get_meta_domain",
    "summarize_intolerant_regions",
}


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback."""
    if tool in _QUERY_TOOLS:
        value = str(arguments.get("query", "") or arguments.get("gene", ""))
        if value and not looks_like_transcript_query(value):
            return [cmd("resolve_transcript", query=value), cmd("get_server_capabilities")]
    if tool in _LANDSCAPE_TOOLS:
        transcript_id = str(arguments.get("transcript_id", ""))
        if transcript_id and error_code == "not_found":
            # The landscape is not built yet: request a build, then poll for it.
            return [
                cmd("request_tolerance_landscape", transcript_id=transcript_id),
                cmd("get_tolerance_landscape", transcript_id=transcript_id),
            ]
    if error_code == "upstream_unavailable":
        return [cmd("get_diagnostics")]
    return [cmd("get_server_capabilities")]
