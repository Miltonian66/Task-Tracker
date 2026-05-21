from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения, читаются из переменных окружения / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Task Tracker"
    debug: bool = False

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@db:5432/tasks",
        description="DSN базы данных (async-драйвер).",
    )

    redis_url: str = Field(
        default="redis://redis:6379/0",
        description="DSN Redis для кэша списка задач.",
    )

    cache_list_ttl_seconds: int = 30
    cache_enabled: bool = True

    list_default_limit: int = 100


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
