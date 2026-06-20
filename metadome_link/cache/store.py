"""On-disk SQLite result cache and in-memory TTL/LRU cache for metadome-link.

Two cache layers are provided:

* ``TTLCache`` — a generic, synchronous, key→value in-memory cache with a
  per-entry TTL and LRU eviction.  An injectable *clock* function lets tests
  simulate time without real sleeps, and ``ttl=0`` acts as an immediate-miss
  sentinel.

* ``ResultCache`` — an SQLite-backed store for completed MetaDome tolerance
  landscapes, with a ``TTLCache`` LRU layer in front.  Keying is by
  ``(transcript_id, data_version)`` so a different ``data_version`` always
  misses, allowing safe schema bumps.

CLI entry point ``main()`` (the ``metadome-link-cache`` script) exposes
``status`` and ``clear`` sub-commands; ``warm`` is a stub for a future task.
"""

from __future__ import annotations

import json
import sqlite3
import time as _time_module
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from metadome_link.config import settings
from metadome_link.constants import METADOME_DATA_VERSION

# ---------------------------------------------------------------------------
# TTLCache
# ---------------------------------------------------------------------------

class TTLCache[K, V]:
    """A generic in-memory LRU cache with per-entry TTL expiry.

    Args:
        maxsize: Maximum number of entries.  ``0`` disables the cache entirely
            (every ``set`` is a no-op; every ``get`` returns ``None``).
        ttl: Time-to-live in seconds.  ``0`` (or any non-positive value) means
            entries expire immediately — every ``get`` returns ``None``.  This
            enables deterministic testing without real sleeps.
        clock: Optional callable returning the current time as a float
            (monotonic seconds).  Defaults to ``time.monotonic``; inject a
            controllable function in tests.
    """

    def __init__(
        self,
        *,
        maxsize: int,
        ttl: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Initialise the TTL + LRU cache."""
        self._maxsize = maxsize
        self._ttl = ttl
        self._clock: Callable[[], float] = clock if clock is not None else _time_module.monotonic
        # OrderedDict preserves insertion/access order for LRU semantics.
        # Values are (expires_at, payload) tuples.
        self._store: OrderedDict[Any, tuple[float, Any]] = OrderedDict()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, key: K) -> V | None:
        """Return the stored value for *key*, or ``None`` on miss or expiry."""
        if self._maxsize <= 0 or self._ttl <= 0:
            return None
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._store[key]
            return None
        # Move to most-recently-used end
        self._store.move_to_end(key)
        result: V = value
        return result

    def set(self, key: K, value: V) -> None:
        """Store *value* under *key*, evicting the LRU entry if the cache is full."""
        if self._maxsize <= 0 or self._ttl <= 0:
            return
        expires_at = self._clock() + self._ttl
        self._store[key] = (expires_at, value)
        self._store.move_to_end(key)
        # Evict until within capacity
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._store.clear()

    @property
    def size(self) -> int:
        """Current number of entries (including potentially-expired ones)."""
        return len(self._store)


# ---------------------------------------------------------------------------
# ResultCache
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    transcript_id TEXT NOT NULL,
    data_version  TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    json          TEXT NOT NULL,
    PRIMARY KEY (transcript_id, data_version)
);
"""


class ResultCache:
    """SQLite-backed store for completed MetaDome tolerance landscapes.

    An in-memory LRU front-cache (``TTLCache``) sits in front of the SQLite
    database.  Cache keys are ``(transcript_id, data_version)`` — a change in
    ``data_version`` always causes a miss, enabling safe schema bumps.

    The parent directory of ``db_path`` is created automatically.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``settings.cache.db_path``.
        data_version: Pinned data-version string used as the secondary key.
            Defaults to ``METADOME_DATA_VERSION``.
        lru_maxsize: In-memory LRU capacity.  Defaults to
            ``settings.cache.lru_results``.  Pass ``0`` to disable the LRU.
    """

    def __init__(
        self,
        db_path: str | None = None,
        data_version: str | None = None,
        lru_maxsize: int | None = None,
    ) -> None:
        """Open (or create) the SQLite database and the in-memory LRU layer."""
        self._db_path = db_path if db_path is not None else settings.cache.db_path
        self._data_version = (
            data_version if data_version is not None else METADOME_DATA_VERSION
        )
        _maxsize = lru_maxsize if lru_maxsize is not None else settings.cache.lru_results
        # LRU entries live indefinitely (no TTL on disk entries — disk is the
        # authoritative source; LRU is purely an acceleration layer).
        self._lru: TTLCache[str, dict[str, Any]] = TTLCache(
            maxsize=_maxsize, ttl=float("inf")
        )
        self._closed = False

        # Ensure parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Open SQLite connection (check_same_thread=False is safe here because
        # ResultCache is used synchronously from a single thread/coroutine in
        # the services layer; if multi-thread use is needed, callers must
        # serialise externally).
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_result(self, transcript_id: str) -> dict[str, Any] | None:
        """Return the cached landscape for *transcript_id*, or ``None`` on miss.

        Checks the in-memory LRU first; falls back to SQLite.
        """
        cached = self._lru.get(transcript_id)
        if cached is not None:
            return cached

        row = self._conn.execute(
            "SELECT json FROM results WHERE transcript_id = ? AND data_version = ?",
            (transcript_id, self._data_version),
        ).fetchone()
        if row is None:
            return None
        value: dict[str, Any] = json.loads(row[0])
        # Warm the LRU
        self._lru.set(transcript_id, value)
        return value

    def put_result(self, transcript_id: str, landscape: dict[str, Any]) -> None:
        """Store *landscape* for *transcript_id*, replacing any existing entry."""
        fetched_at = datetime.now(UTC).isoformat()
        blob = json.dumps(landscape, ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO results (transcript_id, data_version, fetched_at, json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (transcript_id, data_version) DO UPDATE
                SET fetched_at = excluded.fetched_at,
                    json       = excluded.json
            """,
            (transcript_id, self._data_version, fetched_at, blob),
        )
        self._conn.commit()
        self._lru.set(transcript_id, landscape)

    def cached_transcript_ids(self) -> list[str]:
        """Return all transcript ids stored for the current data_version."""
        rows = self._conn.execute(
            "SELECT transcript_id FROM results WHERE data_version = ? ORDER BY transcript_id",
            (self._data_version,),
        ).fetchall()
        return [r[0] for r in rows]

    def stats(self) -> dict[str, Any]:
        """Return a summary of cache state.

        Keys:
            ``on_disk``: number of entries in SQLite for the current version.
            ``lru_size``: number of entries in the in-memory LRU.
            ``data_version``: the pinned data version string.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM results WHERE data_version = ?",
            (self._data_version,),
        ).fetchone()
        on_disk: int = row[0] if row else 0
        return {
            "on_disk": on_disk,
            "lru_size": self._lru.size,
            "data_version": self._data_version,
        }

    def clear(self) -> int:
        """Delete all entries for the current data_version.

        Returns the number of deleted rows.
        """
        cur = self._conn.execute(
            "DELETE FROM results WHERE data_version = ?",
            (self._data_version,),
        )
        self._conn.commit()
        self._lru.clear()
        return cur.rowcount

    def close(self) -> None:
        """Close the SQLite connection.  Idempotent — safe to call multiple times."""
        if not self._closed:
            self._conn.close()
            self._closed = True


# ---------------------------------------------------------------------------
# CLI (metadome-link-cache)
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="metadome-link-cache",
    help="Manage the MetaDome result cache.",
    add_completion=False,
)


@app.command()
def status() -> None:
    """Print cache statistics (on-disk count, LRU size, data version)."""
    cache = ResultCache()
    try:
        s = cache.stats()
    finally:
        cache.close()
    typer.echo(f"data_version : {s['data_version']}")
    typer.echo(f"on_disk      : {s['on_disk']}")
    typer.echo(f"lru_size     : {s['lru_size']}")


@app.command()
def clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Clear all cached results for the current data version."""
    if not yes:
        typer.confirm("This will delete all cached results. Continue?", abort=True)
    cache = ResultCache()
    try:
        count = cache.clear()
    finally:
        cache.close()
    typer.echo(f"Cleared {count} cached result(s).")


@app.command()
def warm(
    genes: list[str] = typer.Argument(..., help="Gene symbol(s) to pre-warm."),
) -> None:
    """Pre-warm the cache for the given gene(s). (Not yet implemented.)"""
    typer.echo("warm: not yet implemented — full wiring is a later task.")
    for gene in genes:
        typer.echo(f"  skipping: {gene}")


def main() -> None:
    """Entry point for the ``metadome-link-cache`` console script."""
    app()
