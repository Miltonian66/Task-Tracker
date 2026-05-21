from __future__ import annotations

from collections.abc import AsyncIterator

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import StaticPool

from app import cache as cache_module
from app import database as db_module
from app.cache import TaskListCache
from app.main import create_app


@pytest_asyncio.fixture
async def app_instance() -> AsyncIterator:
    """Поднимает приложение поверх SQLite в памяти и fakeredis."""
    # Изолированная in-memory БД с общим пулом
    db_module.init_engine(
        "sqlite+aiosqlite:///:memory:",
        engine_kwargs={
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
    )
    await db_module.create_all()

    # Fake Redis
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    cache_module.set_cache_for_tests(
        TaskListCache(fake_redis, ttl_seconds=60, enabled=True),
    )

    app = create_app()
    # lifespan уже отработает все init-и заново, но они идемпотентны: безопасно.
    yield app

    await db_module.dispose_engine()
    await fake_redis.aclose()
    cache_module.set_cache_for_tests(TaskListCache(None, ttl_seconds=60, enabled=False))


@pytest_asyncio.fixture
async def client(app_instance) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_task_payload() -> dict:
    return {
        "title": "Починить регистрацию",
        "description": "Падает на длинном email",
        "assignee": "m.ivanov",
    }
