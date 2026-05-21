from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.cache import TaskListCache, get_cache
from app.config import get_settings
from app.database import get_session
from app.enums import TaskStatus
from app.schemas import TaskCreate, TaskRead, TaskStatusUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CacheDep = Annotated[TaskListCache, Depends(get_cache)]

# Жёсткая верхняя граница пагинации - часть публичного контракта API.
# Превышение = 422.
MAX_LIST_LIMIT = 500


@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать задачу",
)
async def create_task(
    payload: TaskCreate,
    session: SessionDep,
    cache: CacheDep,
) -> TaskRead:
    task = await crud.create_task(session, payload)
    await cache.invalidate()
    return TaskRead.model_validate(task)


@router.get(
    "",
    response_model=list[TaskRead],
    summary="Список задач с фильтрами и пагинацией",
)
async def list_tasks(
    session: SessionDep,
    cache: CacheDep,
    status_filter: Annotated[
        TaskStatus | None,
        Query(alias="status", description="Фильтр по статусу."),
    ] = None,
    assignee: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Фильтр по исполнителю."),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            ge=1,
            le=MAX_LIST_LIMIT,
            description=(
                f"Сколько задач вернуть (1..{MAX_LIST_LIMIT}). "
                "По умолчанию — list_default_limit из конфига."
            ),
        ),
    ] = None,
    offset: Annotated[
        int,
        Query(ge=0, description="Сколько задач пропустить."),
    ] = 0,
) -> list[TaskRead]:
    settings = get_settings()
    effective_limit = limit if limit is not None else settings.list_default_limit

    status_str = status_filter.value if status_filter else None

    cached = await cache.get(
        status=status_str, assignee=assignee, limit=effective_limit, offset=offset
    )
    if cached is not None:
        return [TaskRead.model_validate(item) for item in cached]

    tasks = await crud.list_tasks(
        session,
        status=status_filter,
        assignee=assignee,
        limit=effective_limit,
        offset=offset,
    )
    result = [TaskRead.model_validate(t) for t in tasks]

    await cache.set(
        [item.model_dump(mode="json") for item in result],
        status=status_str,
        assignee=assignee,
        limit=effective_limit,
        offset=offset,
    )
    return result


@router.get(
    "/{task_id}",
    response_model=TaskRead,
    summary="Получить задачу по id",
)
async def get_task(task_id: uuid.UUID, session: SessionDep) -> TaskRead:
    task = await crud.get_task(session, task_id)
    return TaskRead.model_validate(task)


@router.patch(
    "/{task_id}/status",
    response_model=TaskRead,
    summary="Изменить статус задачи",
)
async def change_status(
    task_id: uuid.UUID,
    payload: TaskStatusUpdate,
    session: SessionDep,
    cache: CacheDep,
) -> TaskRead:
    task = await crud.update_status(session, task_id, payload.status)
    await cache.invalidate()
    return TaskRead.model_validate(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить задачу",
)
async def delete_task(task_id: uuid.UUID, session: SessionDep, cache: CacheDep) -> Response:
    await crud.delete_task(session, task_id)
    await cache.invalidate()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
