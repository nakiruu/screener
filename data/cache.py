"""
data/cache.py
Simple JSON file cache with per-key TTL support.
"""

import json
import time
from pathlib import Path


class JSONCache:
    def __init__(self, cache_dir: str, ttl: int = 86400):
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            age = time.time() - data.get("_cached_at", 0)
            if age < self.ttl:
                return data
        except Exception:
            pass
        return None

    def set(self, key: str, data: dict) -> None:
        p = self._path(key)
        try:
            payload = {"_cached_at": time.time(), **data}
            p.write_text(json.dumps(payload, indent=2))
        except Exception:
            pass

    def invalidate(self, key: str) -> None:
        p = self._path(key)
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    def clear(self) -> None:
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
            except Exception:
                pass


# Module-level convenience caches matching CLAUDE.md TTL specs
price_cache = JSONCache("data/price_cache",  ttl=14_400)   # 4 hours
fund_cache  = JSONCache("data/fund_cache",   ttl=86_400)   # 24 hours
