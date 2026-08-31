"""Bounded, identity-safe asynchronous cache for transcript resolutions."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any


class TranscriptCache:
    """TTL/LRU cache that deduplicates concurrent fetches and isolates callers."""

    def __init__(self, *, ttl_seconds: int, maxsize: int) -> None:
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._values: OrderedDict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = (
            OrderedDict()
        )
        self._inflight: dict[tuple[str, str], asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def get(
        self,
        key: tuple[str, str],
        fetch: Callable[[], Awaitable[list[dict[str, Any]]]],
    ) -> list[dict[str, Any]]:
        """Return a deep-copied cached value or one validated fetch result."""
        if self._ttl <= 0 or self._maxsize <= 0:
            return deepcopy(await fetch())
        while True:
            async with self._lock:
                cached = self._values.get(key)
                if cached is not None and cached[0] > time.monotonic():
                    self._values.move_to_end(key)
                    return deepcopy(cached[1])
                if cached is not None:
                    self._values.pop(key, None)
                waiter = self._inflight.get(key)
                if waiter is None:
                    self._inflight[key] = asyncio.Event()
                    break
            await waiter.wait()
        try:
            value = await fetch()
            async with self._lock:
                self._values[key] = (time.monotonic() + self._ttl, deepcopy(value))
                self._values.move_to_end(key)
                while len(self._values) > self._maxsize:
                    self._values.popitem(last=False)
            return deepcopy(value)
        finally:
            async with self._lock:
                event = self._inflight.pop(key)
                event.set()
