"""Cache service: Valkey/Redis if configured, else an in-memory TTL fallback."""

import hashlib
import time
from typing import Optional

from app.core.config import settings
from app.core.logging import logger

try:
    from redis.asyncio import Redis

    REDIS_AVAILABLE = True
except ImportError:
    Redis = None
    REDIS_AVAILABLE = False


class InMemoryCacheService:
    """Simple in-memory TTL cache."""

    def __init__(self, default_ttl: int = 60):
        self._cache: dict[str, tuple[float, str]] = {}
        self._default_ttl = default_ttl

    async def initialize(self) -> None:
        logger.info("cache_initialized", backend="in_memory", ttl=self._default_ttl)

    async def get(self, key: str) -> Optional[str]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._cache[key]
            return None
        return value

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        self._cache[key] = (time.monotonic() + (ttl or self._default_ttl), value)

    async def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    async def close(self) -> None:
        self._cache.clear()


class ValkeyCacheService:
    """Redis/Valkey-backed distributed cache."""

    def __init__(self, default_ttl: int = 60):
        self._client = None
        self._default_ttl = default_ttl

    async def initialize(self) -> None:
        client = Redis(
            host=settings.VALKEY_HOST,
            port=settings.VALKEY_PORT,
            db=settings.VALKEY_DB,
            password=settings.VALKEY_PASSWORD or None,
            decode_responses=True,
        )
        await client.ping()
        self._client = client
        logger.info("cache_initialized", backend="redis", host=settings.VALKEY_HOST)

    async def get(self, key: str) -> Optional[str]:
        if not self._client:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.warning("cache_get_failed", key=key, error=str(e))
            return None

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        if not self._client:
            return
        try:
            await self._client.set(key, value, ex=(ttl or self._default_ttl))
        except Exception as e:
            logger.warning("cache_set_failed", key=key, error=str(e))

    async def delete(self, key: str) -> None:
        if not self._client:
            return
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.warning("cache_delete_failed", key=key, error=str(e))

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()


def _create_cache_service():
    ttl = settings.CACHE_TTL_SECONDS
    if settings.VALKEY_HOST and REDIS_AVAILABLE:
        return ValkeyCacheService(default_ttl=ttl)
    if settings.VALKEY_HOST and not REDIS_AVAILABLE:
        logger.warning("redis_client_not_installed", hint="pip install redis")
    return InMemoryCacheService(default_ttl=ttl)


def cache_key(prefix: str, *parts: str) -> str:
    """Build a deterministic, hashed cache key."""
    raw = ":".join(parts)
    hashed = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{prefix}:{hashed}"


cache_service = _create_cache_service()
