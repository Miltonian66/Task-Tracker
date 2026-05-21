from __future__ import annotations

import contextlib
import logging
from typing import Any

import orjson
import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger(__name__)

# Ключ-счётчик версии списка задач. На каждое изменение делаем INCR,
# благодаря чему все ранее закэшированные комбинации фильтров мгновенно
# становятся протухшими — нет нужды сканировать пространство ключей.
_VERSION_KEY = "tasks:list:version"
_LIST_KEY_PREFIX = "tasks:list"


class TaskListCache:
    """Тонкая обёртка над Redis для кэша GET /tasks."""

    def __init__(self, client: redis.Redis | None, *, ttl_seconds: int, enabled: bool) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._enabled = enabled and client is not None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _current_version(self) -> int:
        """Возвращает текущую версию списочного кэша."""
        assert self._client is not None
        raw = await self._client.get(_VERSION_KEY)
        return int(raw) if raw is not None else 0

    def _build_key(
        self,
        version: int,
        *,
        status: str | None,
        assignee: str | None,
        limit: int,
        offset: int,
    ) -> str:
        return (
            f"{_LIST_KEY_PREFIX}:v{version}"
            f":status={status or '_'}"
            f":assignee={assignee or '_'}"
            f":limit={limit}:offset={offset}"
        )

    async def get(
        self,
        *,
        status: str | None,
        assignee: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]] | None:
        if not self._enabled:
            return None
        try:
            version = await self._current_version()
            key = self._build_key(
                version, status=status, assignee=assignee, limit=limit, offset=offset
            )
            assert self._client is not None
            raw = await self._client.get(key)
            if raw is None:
                return None
            return orjson.loads(raw)
        except Exception as exc:
            # Кэш — оптимизация, не источник истины: молча падаем в БД.
            logger.warning("Redis GET failed: %s", exc)
            return None

    async def set(
        self,
        payload: list[dict[str, Any]],
        *,
        status: str | None,
        assignee: str | None,
        limit: int,
        offset: int,
    ) -> None:
        if not self._enabled:
            return
        try:
            version = await self._current_version()
            key = self._build_key(
                version, status=status, assignee=assignee, limit=limit, offset=offset
            )
            assert self._client is not None
            await self._client.set(key, orjson.dumps(payload), ex=self._ttl)
        except Exception as exc:
            logger.warning("Redis SET failed: %s", exc)

    async def invalidate(self) -> None:
        """Инвалидирует весь списочный кэш через инкремент версионного ключа.

        Это единственное место, где сбой Redis влияет на корректность данных:
        если INCR не дошёл, старые ключи останутся актуальными до их TTL.
        Поэтому пишем в лог уровня ERROR — на проде это должно подсвечиваться
        алертом. Худший случай несвежести ограничен TTL ключей (см. config).
        """
        if not self._enabled:
            return
        try:
            assert self._client is not None
            await self._client.incr(_VERSION_KEY)
        except Exception as exc:
            logger.error(
                "Cache invalidation failed; stale list cache may persist up to TTL: %s",
                exc,
            )


_cache: TaskListCache | None = None


async def init_cache() -> TaskListCache:
    """Создаёт глобальный экземпляр кэша. Падение Redis = кэш выключен."""
    global _cache
    settings = get_settings()

    if not settings.cache_enabled:
        _cache = TaskListCache(None, ttl_seconds=settings.cache_list_ttl_seconds, enabled=False)
        return _cache

    client: redis.Redis | None = None
    try:
        client = redis.from_url(settings.redis_url, decode_responses=False)
        await client.ping()
        # Атомарная инициализация версионного ключа (NX = только если нет).
        # Никаких race с конкурентным INCR: SETNX либо создаёт, либо no-op.
        await client.set(_VERSION_KEY, 0, nx=True)
    except Exception as exc:
        logger.warning("Redis unreachable, cache disabled: %s", exc)
        if client is not None:
            await client.aclose()
        client = None

    _cache = TaskListCache(
        client,
        ttl_seconds=settings.cache_list_ttl_seconds,
        enabled=client is not None,
    )
    return _cache


def get_cache() -> TaskListCache:
    if _cache is None:
        # Используется в тестах — если init не вызван, делаем no-op кэш.
        return TaskListCache(None, ttl_seconds=60, enabled=False)
    return _cache


def set_cache_for_tests(cache: TaskListCache) -> None:
    """Тестовая инъекция (например, fakeredis)."""
    global _cache
    _cache = cache


async def dispose_cache() -> None:
    global _cache
    if _cache is not None and _cache._client is not None:
        with contextlib.suppress(Exception):
            await _cache._client.aclose()
    _cache = None
