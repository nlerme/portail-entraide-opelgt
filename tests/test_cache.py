from pathlib import Path

from app.pieces.services.cache import PersistentCache


def test_persistent_cache_roundtrip(tmp_path: Path):
    cache = PersistentCache(tmp_path / "cache.sqlite3")
    cache.set("test", "key", {"value": 42}, 60)
    assert cache.get("test", "key") == {"value": 42}
