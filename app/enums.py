from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """Жизненный цикл задачи.

    Порядок строго линейный: todo -> in_progress -> review -> done.
    Разрешён ровно один переход вперёд на соседний шаг, откат назад запрещён.
    """

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"

    @property
    def rank(self) -> int:
        return _STATUS_ORDER[self]

    def is_terminal(self) -> bool:
        return self is TaskStatus.DONE

    def next(self) -> TaskStatus | None:
        """Следующий допустимый статус или None для терминального."""
        return _NEXT_STATUS.get(self)


_STATUS_ORDER: dict[TaskStatus, int] = {
    TaskStatus.TODO: 0,
    TaskStatus.IN_PROGRESS: 1,
    TaskStatus.REVIEW: 2,
    TaskStatus.DONE: 3,
}

_NEXT_STATUS: dict[TaskStatus, TaskStatus] = {
    TaskStatus.TODO: TaskStatus.IN_PROGRESS,
    TaskStatus.IN_PROGRESS: TaskStatus.REVIEW,
    TaskStatus.REVIEW: TaskStatus.DONE,
}


def is_valid_transition(current: TaskStatus, new: TaskStatus) -> bool:
    """Разрешает только переход на соседний статус вперёд."""
    return new == current.next()
