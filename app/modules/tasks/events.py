"""Лента задачи пишется синхронно. Outbox — только для уведомлений."""

from app.core.db import utcnow
from app.modules.tasks.models import TaskEvent

CREATED = "created"
STATUS = "status"
ASSIGNED = "assigned"
COMMENT = "comment"
CHECKLIST = "checklist"
DEADLINE = "deadline"
ATTACHMENT = "attachment"
UPDATED = "updated"


def register() -> None:
    return


def add_event(session, task_id: int, user_id: int | None, kind: str, body: str = "") -> None:
    session.add(
        TaskEvent(
            task_id=task_id,
            kind=kind,
            body=body or "",
            user_id=user_id,
            created_at=utcnow(),
        )
    )
