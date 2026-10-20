"""Построение dict-ответов модуля задач (сериализация строк в API-ответ).

``_task_brief_from`` — чистая функция без обращений к базе: и список
доски, и карточка задачи собираются из уже загруженных строк.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import FileLink, StoredFile
from app.modules.tasks.models import ChecklistItem, Task, TaskEvent, TaskRef, TaskStatus
from app.modules.tasks.service._queries import _checks, _events, _tags_by_task
from app.modules.tasks.service._validators import _progress


def _status_out(row: TaskStatus) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "color": row.color,
        "is_closed": bool(row.is_closed),
        "position": row.position,
    }


def _check_out(row: ChecklistItem) -> dict:
    return {"id": row.id, "title": row.title, "done": bool(row.done), "position": row.position}


def _event_out(row: TaskEvent) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "body": row.body or "",
        "user_id": row.user_id,
        "created_at": row.created_at.isoformat(),
    }


def _ref_out(row: TaskRef) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "target_id": row.target_id,
        "file_id": row.file_id,
        "original_name": row.title,
        "size": None,
    }


def _task_brief_from(task: Task, checks: list[ChecklistItem], tags: list[dict]) -> dict:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "status_id": task.status_id,
        "title": task.title,
        "assignee_id": task.assignee_id,
        "priority": task.priority,
        "progress": _progress(task, checks),
        "progress_mode": task.progress_mode,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "repeat_kind": task.repeat_kind or "",
        "repeat_interval": task.repeat_interval or 1,
        "repeat_until": task.repeat_until.isoformat() if task.repeat_until else None,
        "position": task.position,
        "checklist_done": sum(1 for item in checks if item.done),
        "checklist_total": len(checks),
        "tags": tags,
        "updated_at": task.updated_at.isoformat(),
    }


def _task_brief(session: Session, task: Task) -> dict:
    checks = _checks(session, task.id)
    tags = _tags_by_task(session, [task.id]).get(task.id, [])
    return _task_brief_from(task, checks, tags)


def _task_full(session: Session, task: Task) -> dict:
    data = _task_brief(session, task)
    data["description"] = task.description or ""
    data["progress_manual"] = task.progress_manual
    data["created_at"] = task.created_at.isoformat()
    data["closed_at"] = task.closed_at.isoformat() if task.closed_at else None
    data["checklist"] = [_check_out(row) for row in _checks(session, task.id)]
    data["events"] = [_event_out(row) for row in _events(session, task.id)]
    data["files"] = _files(session, task.id)
    return data


def _files(session: Session, task_id: int) -> list[dict]:
    items = [
        _ref_out(row)
        for row in session.scalars(select(TaskRef).where(TaskRef.task_id == task_id).order_by(TaskRef.id.asc())).all()
    ]
    rows = session.execute(
        select(FileLink, StoredFile)
        .join(StoredFile, StoredFile.id == FileLink.file_id)
        .where(FileLink.module == "tasks", FileLink.entity_type == "task", FileLink.entity_id == task_id)
        .order_by(FileLink.id.asc())
    ).all()
    for link, stored in rows:
        items.append(
            {
                "id": link.id,
                "kind": "file",
                "target_id": None,
                "file_id": stored.id,
                "original_name": stored.original_name,
                "size": stored.size,
            }
        )
    return items


def _event_payload(task: Task, status_id: int | None = None) -> dict:
    payload = {
        "task_id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "assignee_id": task.assignee_id,
        "status_id": status_id if status_id is not None else task.status_id,
    }
    if task.deadline is not None:
        payload["deadline"] = task.deadline.isoformat()
    return payload
