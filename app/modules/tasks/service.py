from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.bridge import materialize
from app.core.events_catalog import (
    TASK_ASSIGNED,
    TASK_CHECKLIST_ADDED,
    TASK_CHECKLIST_DONE,
    TASK_COMMENT,
    TASK_CREATED,
    TASK_DEADLINE_CHANGED,
    TASK_DEADLINE_SOON,
    TASK_DELETED,
    TASK_FILE,
    TASK_OVERDUE,
    TASK_STATUS_CHANGED,
    TASK_UPDATED,
)
from app.core.logging import log_scope, logger
from app.core.models import FileLink, StoredFile, User
from app.core.outbox import enqueue
from app.core.settings_store import get, get_int, get_str
from app.modules.projects.service import touch_project
from app.modules.tasks import events
from app.modules.tasks.models import ChecklistItem, Tag, Task, TaskEvent, TaskNotice, TaskRef, TaskStatus, TaskTag


def seed_project(session: Session, project) -> None:
    seed_project_id(session, project.id)


def seed_project_id(session: Session, project_id: int) -> None:
    exists = session.scalars(select(TaskStatus.id).where(TaskStatus.project_id == project_id)).first()
    if exists is not None:
        return
    raw = get("tasks", "statuses.defaults")
    if not isinstance(raw, list):
        return
    name_limit = get_int("tasks", "status.name.max_length")
    color_limit = get_int("tasks", "status.color.max_length")
    position = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        session.add(
            TaskStatus(
                project_id=project_id,
                name=name[:name_limit],
                color=str(item.get("color") or "")[:color_limit],
                is_closed=bool(item.get("is_closed")),
                position=position,
                created_at=utcnow(),
            )
        )
        position += 1
    session.flush()


def backfill_statuses() -> None:
    from app.core.db import session_scope
    from app.modules.projects.service import list_project_ids

    with session_scope() as session:
        for project_id in list_project_ids(session):
            seed_project_id(session, project_id)


def load_task(session: Session, task_id: int) -> Task | None:
    return session.get(Task, task_id)


def list_statuses(session: Session, project_id: int) -> list[dict]:
    rows = _statuses(session, project_id)
    return [_status_out(row) for row in rows]


def create_status(session: Session, project_id: int, user_id: int, name: str, color: str, is_closed: bool) -> dict:
    rows = _statuses(session, project_id)
    row = TaskStatus(
        project_id=project_id,
        name=_clean(name, "status.name.max_length", "Укажите название колонки"),
        color=_color(color),
        is_closed=is_closed,
        position=len(rows),
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("tasks", "status.create", user_id=user_id):
        logger.info("status created id={} project={}", row.id, project_id)
    return _status_out(row)


def update_status(session: Session, project_id: int, user_id: int, status_id: int, fields: dict) -> dict:
    row = _status(session, project_id, status_id)
    if "name" in fields and fields["name"] is not None:
        row.name = _clean(fields["name"], "status.name.max_length", "Укажите название колонки")
    if "color" in fields and fields["color"] is not None:
        row.color = _color(fields["color"])
    if "is_closed" in fields and fields["is_closed"] is not None:
        row.is_closed = bool(fields["is_closed"])
        _sync_closed_flags(session, project_id, row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("tasks", "status.update", user_id=user_id):
        logger.info("status updated id={} project={}", row.id, project_id)
    return _status_out(row)


def delete_status(session: Session, project_id: int, user_id: int, status_id: int) -> None:
    row = _status(session, project_id, status_id)
    used = session.scalar(select(func.count()).select_from(Task).where(Task.status_id == row.id)) or 0
    if used:
        raise HTTPException(status_code=400, detail="В колонке есть задачи")
    session.delete(row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("tasks", "status.delete", user_id=user_id):
        logger.info("status deleted id={} project={}", status_id, project_id)


def order_statuses(session: Session, project_id: int, user_id: int, ids: list[int]) -> list[dict]:
    rows = {row.id: row for row in _statuses(session, project_id)}
    if set(ids) != set(rows):
        raise HTTPException(status_code=400, detail="Передайте все колонки проекта")
    for position, status_id in enumerate(ids):
        rows[status_id].position = position
    session.flush()
    with log_scope("tasks", "status.order", user_id=user_id):
        logger.info("statuses ordered project={}", project_id)
    return [_status_out(rows[status_id]) for status_id in ids]


def list_tags(session: Session, project_id: int) -> list[dict]:
    rows = session.scalars(select(Tag).where(Tag.project_id == project_id).order_by(Tag.name.asc(), Tag.id.asc())).all()
    return [_tag_out(row) for row in rows]


def create_tag(session: Session, project_id: int, user_id: int, name: str) -> dict:
    text = _clean(name, "tag.name.max_length", "Укажите метку")
    rows = session.scalars(select(Tag).where(Tag.project_id == project_id)).all()
    if any(row.name.casefold() == text.casefold() for row in rows):
        raise HTTPException(status_code=400, detail="Такая метка уже есть")
    row = Tag(project_id=project_id, name=text)
    session.add(row)
    session.flush()
    with log_scope("tasks", "tag.create", user_id=user_id):
        logger.info("tag created id={} project={}", row.id, project_id)
    return _tag_out(row)


def delete_tag(session: Session, project_id: int, user_id: int, tag_id: int) -> None:
    row = session.get(Tag, tag_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Метка не найдена")
    for link in session.scalars(select(TaskTag).where(TaskTag.tag_id == row.id)).all():
        session.delete(link)
    session.delete(row)
    session.flush()
    with log_scope("tasks", "tag.delete", user_id=user_id):
        logger.info("tag deleted id={} project={}", tag_id, project_id)


def list_tasks(session: Session, project_id: int) -> dict:
    limit = get_int("tasks", "board.max_tasks", project_id=project_id)
    rows = session.scalars(
        select(Task).where(Task.project_id == project_id).order_by(Task.position.asc(), Task.id.asc()).limit(limit)
    ).all()
    task_ids = [row.id for row in rows]
    checks_by_task = _checks_by_tasks(session, task_ids)
    tags_by_task = _tags_by_task(session, task_ids)
    items = []
    for row in rows:
        checks = checks_by_task.get(row.id, [])
        tags = tags_by_task.get(row.id, [])
        items.append(_task_brief_from(row, checks, tags))
    return {"items": items, "truncated": len(rows) >= limit}


def get_task(session: Session, project_id: int, task_id: int) -> dict:
    return _task_full(session, _task(session, project_id, task_id))
