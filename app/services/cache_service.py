# app/services/cache_service.py
# Redis-backed cache with automatic in-memory fallback when Redis is unavailable.
# This means the app works perfectly without a running Redis server —
# it just loses cross-process caching and TTL enforcement (acceptable for dev).

import pickle
import time
from typing import Any, Optional
from app.core.config import settings


class _MemoryCache:
    """Simple in-process dict cache used when Redis is unavailable."""

    def __init__(self):
        self._store: dict = {}   # key -> (value_bytes, expires_at)

    def get(self, key: str) -> Optional[bytes]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at and time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def setex(self, key: str, ttl: int, value: bytes):
        self._store[key] = (value, time.time() + ttl)

    def delete(self, key: str):
        self._store.pop(key, None)

    def keys(self, pattern: str = "*"):
        # Very naive pattern match — only supports trailing *
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._store if k.startswith(prefix)]
        return [k for k in self._store if k == pattern]

    def flushdb(self):
        self._store.clear()


def _make_redis_client():
    """Try to create a real Redis client. Return None if Redis is unreachable."""
    try:
        import redis
        client = redis.from_url(settings.REDIS_URL, decode_responses=False,
                                socket_connect_timeout=1)
        client.ping()          # Fail fast if not available
        return client
    except Exception:
        return None


class CacheService:
    """
    Redis-backed cache with automatic in-memory fallback.

    Priority:
      1. Real Redis (if server is running and reachable)
      2. In-process dict cache (no install needed, survives Redis absence)
    """

    def __init__(self):
        self._redis = _make_redis_client()
        if self._redis is None:
            print("[CacheService] Redis unavailable — using in-memory fallback cache.")
            self._mem = _MemoryCache()
        else:
            self._mem = None
        self.default_ttl = 300  # 5 minutes

    @property
    def _client(self):
        """Return whichever backend is active."""
        return self._redis if self._redis is not None else self._mem

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    async def get(self, key: str) -> Optional[Any]:
        try:
            raw = self._client.get(key)
            if raw:
                return pickle.loads(raw)
            return None
        except Exception as e:
            # Don't spam logs — just return None (cache miss)
            return None

    async def set(self, key: str, value: Any, ttl: int = None):
        try:
            ttl = ttl or self.default_ttl
            self._client.setex(key, ttl, pickle.dumps(value))
        except Exception:
            pass  # Cache write failure is non-fatal

    async def delete(self, key: str):
        try:
            self._client.delete(key)
        except Exception:
            pass

    async def exists(self, key: str) -> bool:
        try:
            return bool(self._client.get(key))
        except Exception:
            return False

    async def clear_pattern(self, pattern: str):
        try:
            keys = self._client.keys(pattern)
            for key in keys:
                self._client.delete(key)
        except Exception:
            pass

    async def clear_user_cache(self, user_id: int):
        await self.clear_pattern(f"user:{user_id}:*")
        await self.clear_pattern(f"rec:{user_id}:*")

    async def increment(self, key: str, ttl: int = 60) -> int:
        try:
            val = await self.get(key) or 0
            new_val = val + 1
            await self.set(key, new_val, ttl)
            return new_val
        except Exception:
            return 0

    async def get_stats(self) -> dict:
        backend = "redis" if self._redis is not None else "memory"
        return {"backend": backend, "status": "ok"}
