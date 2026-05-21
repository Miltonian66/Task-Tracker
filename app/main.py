from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.tasks import router as tasks_router
from app.cache import dispose_cache, init_cache
from app.config import get_settings
from app.database import create_all, dispose_engine, init_engine
from app.exceptions import register_exception_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info("Starting %s (debug=%s)", settings.app_name, settings.debug)

    init_engine()
    await create_all()
    await init_cache()
    try:
        yield
    finally:
        await dispose_cache()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Внутренний сервис учёта задач команды. "
            "Поддерживает CRUD и контролируемый жизненный цикл статусов."
        ),
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(tasks_router)

    @app.get("/health", tags=["meta"], summary="Liveness/readiness проба")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
