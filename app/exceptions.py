from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Базовый класс для управляемых ошибок."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "app_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TaskNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "task_not_found"


class InvalidStatusTransitionError(AppError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "invalid_status_transition"


def _error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    payload: dict = {
        "error": {
            "code": error_code,
            "message": message,
        }
    }
    if details:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic-ошибки приходят пачкой — отдаём в одинаковом формате,
        # но с массивом конкретных полей и понятным сообщением.
        # jsonable_encoder нужен потому, что в ctx бывают объекты исключений,
        # которые стандартный json.dumps сериализовать не умеет.
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="validation_error",
            message="Некорректные входные данные.",
            details={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(SQLAlchemyError)
    async def _handle_db(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Внутрь логов идёт полный traceback (для SRE), наружу — только
        # короткий request_id и общий текст. Тип/детали исключения БД
        # сознательно не раскрываем — это утечка реализации.
        request_id = uuid.uuid4().hex
        logger.exception("Database error [request_id=%s]: %s", request_id, exc)
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="database_error",
            message="Внутренняя ошибка базы данных.",
            details={"request_id": request_id},
        )
