from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import TaskStatus, is_valid_transition
from app.exceptions import InvalidStatusTransitionError, TaskNotFoundError
from app.models import Task
from app.schemas import TaskCreate


async def create_task(session: AsyncSession, payload: TaskCreate) -> Task:
    task = Task(
        title=payload.title,
        description=payload.description,
        assignee=payload.assignee,
        status=TaskStatus.TODO,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    *,
    status: TaskStatus | None = None,
    assignee: str | None = None,
    limit: int,
    offset: int,
) -> Sequence[Task]:
    stmt = select(Task).order_by(Task.created_at.desc(), Task.id)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if assignee is not None:
        stmt = stmt.where(Task.assignee == assignee)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(f"Задача с id={task_id} не найдена.")
    return task


async def update_status(
    session: AsyncSession,
    task_id: uuid.UUID,
    new_status: TaskStatus,
) -> Task:
    task = await get_task(session, task_id)

    if new_status == task.status:
        raise InvalidStatusTransitionError(
            f"Задача уже в статусе '{task.status.value}'. Смена не требуется.",
            details={"current": task.status.value, "requested": new_status.value},
        )

    if not is_valid_transition(task.status, new_status):
        expected_next = task.status.next()
        if task.status.is_terminal():
            message = (
                f"Нельзя изменить статус: задача уже завершена "
                f"('{task.status.value}') и переход назад запрещён."
            )
        elif new_status.rank < task.status.rank:
            message = (
                f"Откат статуса запрещён: '{task.status.value}' -> '{new_status.value}'. "
                f"Допустим только переход на следующий шаг: "
                f"'{task.status.value}' -> '{expected_next.value}'."
            )
        else:
            message = (
                f"Прыжки через статусы запрещены: '{task.status.value}' -> "
                f"'{new_status.value}'. Ожидался следующий шаг: "
                f"'{task.status.value}' -> '{expected_next.value}'."
            )
        details = {
            "current": task.status.value,
            "requested": new_status.value,
        }
        if expected_next is not None:
            details["expected"] = expected_next.value
        raise InvalidStatusTransitionError(message, details=details)

    task.status = new_status
    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task_id: uuid.UUID) -> None:
    task = await get_task(session, task_id)
    await session.delete(task)
    await session.commit()
