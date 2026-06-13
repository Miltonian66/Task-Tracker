from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from app import models  # noqa: F401  (регистрирует таблицу Task в Base.metadata)
from app.config import get_settings

# target_metadata: импортируем app.models, чтобы таблицы зарегистрировались в Base.metadata.
from app.database import Base

# Объект конфигурации Alembic, даёт доступ к значениям из alembic.ini.
config = context.config

# Логирование Alembic по конфигу из ini-файла.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL берём из настроек приложения (единый источник правды),
# а не из alembic.ini. Поддерживает DATABASE_URL из окружения / .env.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline-режим: генерация SQL без подключения к БД."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Online-режим: async-движок, миграции через connection.run_sync."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
