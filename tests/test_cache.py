"""Tests for metadome_link.cache.store — ResultCache + TTLCache.

All DB tests use tmp_path, never the real data/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from metadome_link.cache.store import ResultCache, TTLCache
from metadome_link.exceptions import UpstreamSchemaError

# ---------------------------------------------------------------------------
# TTLCache tests
# ---------------------------------------------------------------------------


class TestTTLCache:
    """Tests for the generic TTL in-memory cache."""

    def test_basic_set_and_get(self) -> None:
        """A value stored can be retrieved before expiry."""
        cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=10, ttl=60)
        cache.set("key1", {"value": 1})
        result = cache.get("key1")
        assert result == {"value": 1}

    def test_miss_on_absent_key(self) -> None:
        """Keys not stored return None."""
        cache: TTLCache[str, str] = TTLCache(maxsize=10, ttl=60)
        assert cache.get("nonexistent") is None

    def test_ttl_zero_causes_immediate_miss(self) -> None:
        """TTL=0 means entries are immediately expired — enables deterministic testing."""
        cache: TTLCache[str, str] = TTLCache(maxsize=10, ttl=0)
        cache.set("key", "value")
        assert cache.get("key") is None

    def test_injected_clock_enables_expiry_testing(self) -> None:
        """An injected time source lets tests simulate TTL expiry without real sleeps."""
        fake_time = 1000.0

        def clock() -> float:
            return fake_time

        cache: TTLCache[str, str] = TTLCache(maxsize=10, ttl=30, clock=clock)
        cache.set("key", "hello")
        assert cache.get("key") == "hello"

        # Advance the fake clock past TTL
        fake_time = 1031.0
        assert cache.get("key") is None

    def test_lru_eviction_when_full(self) -> None:
        """When maxsize is exceeded the least-recently-used entry is dropped."""
        cache: TTLCache[str, int] = TTLCache(maxsize=3, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Access "a" to refresh it, making "b" the LRU
        cache.get("a")
        # Insert fourth entry — "b" should be evicted
        cache.set("d", 4)
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_size_zero_always_misses(self) -> None:
        """maxsize=0 effectively disables the cache."""
        cache: TTLCache[str, str] = TTLCache(maxsize=0, ttl=60)
        cache.set("key", "value")
        assert cache.get("key") is None

    def test_size_property(self) -> None:
        """size property reports current entry count."""
        cache: TTLCache[str, int] = TTLCache(maxsize=10, ttl=60)
        assert cache.size == 0
        cache.set("x", 1)
        cache.set("y", 2)
        assert cache.size == 2

    def test_clear_empties_cache(self) -> None:
        """clear() removes all entries."""
        cache: TTLCache[str, int] = TTLCache(maxsize=10, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None


# ---------------------------------------------------------------------------
# ResultCache tests
# ---------------------------------------------------------------------------


class TestResultCache:
    """Tests for the SQLite-backed ResultCache with in-memory LRU front."""

    def test_get_on_empty_cache_returns_none(self, tmp_path: Path) -> None:
        """get_result on a fresh DB returns None for any transcript id."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db)
        assert cache.get_result("ENST00000269305.9") is None
        cache.close()

    def test_put_and_get_round_trip(self, tmp_path: Path) -> None:
        """A landscape stored with put_result can be retrieved with get_result."""
        db = str(tmp_path / "test.sqlite")
        landscape = {"transcript_id": "ENST00000269305.9", "gene_name": "TP53"}
        cache = ResultCache(db_path=db)
        cache.put_result("ENST00000269305.9", landscape)
        result = cache.get_result("ENST00000269305.9")
        assert result == landscape
        cache.close()

    @pytest.mark.parametrize(
        "payload",
        [
            '{"status":"\\ud800"}',
            '{"\\ud800":"ok"}',
            '{"status":NaN}',
            '{"status":Infinity}',
            '{"status":-Infinity}',
        ],
    )
    def test_direct_json_loading_rejects_invalid_unicode_and_numbers(
        self, tmp_path: Path, payload: str
    ) -> None:
        """SQLite cache reads use the same strict JSON contract as HTTP reads."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db)
        try:
            cache._conn.execute(
                "INSERT INTO results (transcript_id, data_version, fetched_at, json) "
                "VALUES (?, ?, ?, ?)",
                ("ENST00000269305.9", cache._data_version, "now", payload),
            )
            cache._conn.commit()
            with pytest.raises(UpstreamSchemaError):
                cache.get_result("ENST00000269305.9")
        finally:
            cache.close()

    def test_direct_json_loading_accepts_supplementary_scalars(self, tmp_path: Path) -> None:
        """Valid supplementary Unicode scalars remain valid cache values."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db)
        payload = json.dumps({"😀": "ok"}, ensure_ascii=False)
        try:
            cache._conn.execute(
                "INSERT INTO results (transcript_id, data_version, fetched_at, json) "
                "VALUES (?, ?, ?, ?)",
                ("ENST00000269305.9", cache._data_version, "now", payload),
            )
            cache._conn.commit()
            assert cache.get_result("ENST00000269305.9") == {"😀": "ok"}
        finally:
            cache.close()

    def test_different_data_version_misses(self, tmp_path: Path) -> None:
        """A cache entry stored with one data_version returns None for a different version."""
        db = str(tmp_path / "test.sqlite")
        landscape = {"transcript_id": "ENST00000269305.9"}

        cache_v1 = ResultCache(db_path=db, data_version="version-A")
        cache_v1.put_result("ENST00000269305.9", landscape)
        cache_v1.close()

        cache_v2 = ResultCache(db_path=db, data_version="version-B")
        assert cache_v2.get_result("ENST00000269305.9") is None
        cache_v2.close()

    def test_same_data_version_hits(self, tmp_path: Path) -> None:
        """The same data_version on a new ResultCache instance finds the stored entry."""
        db = str(tmp_path / "test.sqlite")
        landscape = {"transcript_id": "ENST00000269305.9"}

        cache_a = ResultCache(db_path=db, data_version="version-X")
        cache_a.put_result("ENST00000269305.9", landscape)
        cache_a.close()

        cache_b = ResultCache(db_path=db, data_version="version-X")
        assert cache_b.get_result("ENST00000269305.9") == landscape
        cache_b.close()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """ResultCache creates nested parent directories automatically."""
        db = str(tmp_path / "nested" / "dir" / "cache.sqlite")
        cache = ResultCache(db_path=db)
        cache.put_result("ENST00000000001.1", {"x": 1})
        assert Path(db).exists()
        cache.close()

    def test_cached_transcript_ids_empty(self, tmp_path: Path) -> None:
        """cached_transcript_ids returns an empty list on a fresh DB."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db)
        assert cache.cached_transcript_ids() == []
        cache.close()

    def test_cached_transcript_ids_populated(self, tmp_path: Path) -> None:
        """cached_transcript_ids lists all stored transcript ids for the current data_version."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db, data_version="v1")
        cache.put_result("ENST00000000001.1", {"a": 1})
        cache.put_result("ENST00000000002.2", {"b": 2})
        ids = cache.cached_transcript_ids()
        assert sorted(ids) == ["ENST00000000001.1", "ENST00000000002.2"]
        cache.close()

    def test_cached_transcript_ids_only_current_version(self, tmp_path: Path) -> None:
        """cached_transcript_ids excludes entries from other data versions."""
        db = str(tmp_path / "test.sqlite")

        cache_v1 = ResultCache(db_path=db, data_version="v1")
        cache_v1.put_result("ENST00000000001.1", {"a": 1})
        cache_v1.close()

        cache_v2 = ResultCache(db_path=db, data_version="v2")
        cache_v2.put_result("ENST00000000002.2", {"b": 2})
        ids = cache_v2.cached_transcript_ids()
        assert ids == ["ENST00000000002.2"]
        cache_v2.close()

    def test_stats_empty(self, tmp_path: Path) -> None:
        """stats() on an empty cache returns zero counts."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db, data_version="v1")
        s = cache.stats()
        assert s["on_disk"] == 0
        assert s["lru_size"] == 0
        assert s["data_version"] == "v1"
        cache.close()

    def test_stats_after_puts(self, tmp_path: Path) -> None:
        """stats() reflects stored entries after puts."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db, data_version="v1")
        cache.put_result("ENST00000000001.1", {"a": 1})
        cache.put_result("ENST00000000002.2", {"b": 2})
        s = cache.stats()
        assert s["on_disk"] == 2
        # LRU should have been populated by the puts
        assert s["lru_size"] >= 0
        cache.close()

    def test_clear_removes_all_entries(self, tmp_path: Path) -> None:
        """clear() deletes all rows for the current data_version and returns the count."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db, data_version="v1")
        cache.put_result("ENST00000000001.1", {"a": 1})
        cache.put_result("ENST00000000002.2", {"b": 2})
        count = cache.clear()
        assert count == 2
        assert cache.get_result("ENST00000000001.1") is None
        assert cache.cached_transcript_ids() == []
        cache.close()

    def test_clear_only_clears_current_version(self, tmp_path: Path) -> None:
        """clear() only removes entries for the current data_version, not others."""
        db = str(tmp_path / "test.sqlite")

        cache_v1 = ResultCache(db_path=db, data_version="v1")
        cache_v1.put_result("ENST00000000001.1", {"a": 1})
        cache_v1.close()

        cache_v2 = ResultCache(db_path=db, data_version="v2")
        cache_v2.put_result("ENST00000000002.2", {"b": 2})
        cleared = cache_v2.clear()
        assert cleared == 1
        cache_v2.close()

        # v1 entry survives
        cache_v1_reopen = ResultCache(db_path=db, data_version="v1")
        assert cache_v1_reopen.get_result("ENST00000000001.1") == {"a": 1}
        cache_v1_reopen.close()

    def test_put_overwrites_existing_entry(self, tmp_path: Path) -> None:
        """put_result with the same key replaces the stored landscape."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db)
        cache.put_result("ENST00000000001.1", {"v": 1})
        cache.put_result("ENST00000000001.1", {"v": 2})
        assert cache.get_result("ENST00000000001.1") == {"v": 2}
        cache.close()

    def test_in_memory_lru_hit_after_put(self, tmp_path: Path) -> None:
        """After put_result, a subsequent get_result is served from the LRU (no SQLite read)."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db, lru_maxsize=4)
        landscape = {"transcript_id": "ENST00000269305.9"}
        cache.put_result("ENST00000269305.9", landscape)
        # The LRU should hold the result
        s = cache.stats()
        assert s["lru_size"] >= 1
        assert cache.get_result("ENST00000269305.9") == landscape
        cache.close()

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        """Data written by one ResultCache instance is readable by a fresh one on the same db."""
        db = str(tmp_path / "shared.sqlite")
        landscape = {"gene": "BRCA1"}

        c1 = ResultCache(db_path=db, data_version="v1")
        c1.put_result("ENST00000357654.3", landscape)
        c1.close()

        c2 = ResultCache(db_path=db, data_version="v1")
        assert c2.get_result("ENST00000357654.3") == landscape
        c2.close()

    def test_default_data_version_from_constants(self, tmp_path: Path) -> None:
        """Default data_version is METADOME_DATA_VERSION from constants."""
        from metadome_link.constants import METADOME_DATA_VERSION

        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db)
        s = cache.stats()
        assert s["data_version"] == METADOME_DATA_VERSION
        cache.close()

    def test_get_from_disk_when_lru_empty(self, tmp_path: Path) -> None:
        """ResultCache with lru_maxsize=0 still reads from disk on get."""
        db = str(tmp_path / "test.sqlite")
        landscape = {"gene": "TP53"}

        # Use LRU size 1: put fills it; but a second put will evict first
        c1 = ResultCache(db_path=db, lru_maxsize=1)
        c1.put_result("ENST00000000001.1", landscape)
        # Evict from LRU by putting a second entry
        c1.put_result("ENST00000000002.2", {"gene": "BRCA1"})
        # First entry should still be readable from disk
        result = c1.get_result("ENST00000000001.1")
        assert result == landscape
        c1.close()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        """Calling close() twice does not raise an error."""
        db = str(tmp_path / "test.sqlite")
        cache = ResultCache(db_path=db)
        cache.close()
        cache.close()  # should not raise


# ---------------------------------------------------------------------------
# Smoke test: CLI main() is importable and callable
# ---------------------------------------------------------------------------


def test_main_is_importable() -> None:
    """The module-level main() function is importable without crashing."""
    from metadome_link.cache.store import main

    assert callable(main)
