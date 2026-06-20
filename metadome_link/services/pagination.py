"""Uniform truncation + forward-pagination contract for list-returning tools.

Every list tool returns ``total`` (matches before the cap), ``returned`` (rows in
this payload), ``limit`` (cap applied), ``offset`` (rows skipped), and
``truncated`` (rows remain beyond this page) so an LLM can never mistake a capped
page for a complete list.  When ``truncated`` is true, ``next_offset`` carries the
offset for the next page so a client can advance forward WITHOUT re-sending the
rows it already has (cheaper than widening ``limit``, which re-fetches the head).
When ``truncated`` is false, ``next_offset`` is ``None``.
"""

from __future__ import annotations

from typing import Any


def paginate(
    items: list[Any],
    *,
    limit: int,
    offset: int = 0,
) -> tuple[list[Any], dict[str, Any]]:
    """Slice *items* to the requested page and return the pagination block.

    Parameters
    ----------
    items:
        The full ordered list of items to paginate.  The caller is responsible
        for having already resolved/filtered the list before calling this helper.
    limit:
        Maximum number of items to include in the returned page.
    offset:
        Number of items to skip from the start of *items*.

    Returns
    -------
    tuple[list, dict]
        ``(page, block)`` where *page* is the sliced sub-list and *block* is
        the canonical pagination dict with keys ``{total, returned, limit,
        offset, truncated, next_offset}``.  ``next_offset`` is ``None`` when
        ``truncated`` is ``False``.
    """
    total = len(items)
    page = items[offset : offset + limit]
    returned = len(page)
    consumed = offset + returned
    truncated = consumed < total
    next_offset: int | None = consumed if truncated else None
    block: dict[str, Any] = {
        "total": total,
        "returned": returned,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
        "next_offset": next_offset,
    }
    return page, block
