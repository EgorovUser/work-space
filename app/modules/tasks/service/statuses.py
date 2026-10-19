"""Колонки доски: сид стандартных статусов, CRUD и порядок.

Отдельный файл от задач: колонки живут своей жизнью — создаются при
появлении проекта из ``statuses.defaults`` и не зависят от карточек.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.logging import log_scope, logger
from app.core.settings_store import get, get_int
from app.modules.projects.service import touch_project
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.service._queries import _status, _statuses
from app.modules.tasks.service._serialize import _status_out
from app.modules.tasks.service._validators import _clean, _color


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


def _sync_closed_flags(session: Session, project_id: int, status: TaskStatus) -> None:
    rows = session.scalars(select(Task).where(Task.project_id == project_id, Task.status_id == status.id)).all()
    now = utcnow()
    for task in rows:
        if status.is_closed and task.closed_at is None:
            task.closed_at = now
        if not status.is_closed:
            task.closed_at = None
