from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import TaskStatus


class TaskBase(BaseModel):
    """Поля, общие для запросов и ответов."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Краткое название задачи.",
        examples=["Починить регистрацию"],
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Развёрнутое описание задачи. Обязательное поле (см. README).",
        examples=["Падает на длинном email"],
    )
    assignee: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Исполнитель — логин или имя.",
        examples=["m.ivanov"],
    )

    @field_validator("title", "description", "assignee")
    @classmethod
    def _strip_and_validate(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Поле не может быть пустым или состоять только из пробелов.")
        return stripped


class TaskCreate(TaskBase):
    """Тело POST /tasks. Статус всегда стартует в todo."""


class TaskStatusUpdate(BaseModel):
    """Тело PATCH /tasks/{id}/status."""

    status: TaskStatus = Field(..., description="Новый статус задачи.")


class TaskRead(TaskBase):
    """Ответ API - задача со всеми системными полями."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
