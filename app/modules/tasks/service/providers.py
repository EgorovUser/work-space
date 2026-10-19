"""Интеграция модуля задач с другими частями приложения и фоновая джоба.

Провайдеры собирают данные для чужих экранов: карточка проекта, инбокс
на главном экране, дашборд и поиск проекта. ``check_deadlines`` — джоба
планировщика: пиш ``task.deadline_soon`` и ``task.overdue``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.events_catalog import TASK_DEADLINE_SOON, TASK_OVERDUE
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get, get_int
from app.modules.tasks.models import Task, TaskNotice, TaskStatus
from app.modules.tasks.service._queries import _statuses, _tags_by_task
from app.modules.tasks.service._serialize import _event_payload
from app.modules.tasks.service._validators import _zone
from app.core.db import utcnow


def card_provider(session: Session, project_id: int, user_id: int | None) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    rows = session.execute(
        select(Task.deadline, TaskStatus.is_closed)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(Task.project_id == project_id)
    ).all()
    open_count = 0
    overdue = 0
    nearest = None
    for deadline, closed in rows:
        if closed:
            continue
        open_count += 1
        if deadline is None:
            continue
        if nearest is None or deadline < nearest:
            nearest = deadline
        if deadline.astimezone(zone).date() < today:
            overdue += 1
    return {
        "open_tasks": open_count,
        "overdue_tasks": overdue,
        "nearest_deadline": nearest.isoformat() if nearest is not None else None,
    }


def inbox_provider(session: Session, user_id: int | None, limit: int, project_ids: list[int]) -> list[dict]:
    zone = _zone()
    today = datetime.now(zone).date()
    horizon = get_int("projects", "home.horizon_days")
    cutoff = today + timedelta(days=horizon) if horizon > 0 else None
    cap = limit * 40 if cutoff is not None else limit
    rows = session.execute(
        select(Task, TaskStatus.is_closed)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(
            Task.project_id.in_(project_ids),
            Task.deadline.is_not(None),
            TaskStatus.is_closed.is_(False),
        )
        .order_by(Task.deadline.asc(), Task.id.asc())
        .limit(cap)
    ).all()
    items = []
    for task, _closed in rows:
        due = task.deadline.astimezone(zone).date()
        if cutoff is not None and due > cutoff:
            continue
        items.append(
            {
                "id": task.id,
                "project_id": task.project_id,
                "title": task.title,
                "deadline": task.deadline.isoformat(),
                "overdue": due < today,
            }
        )
        if len(items) >= limit:
            break
    return items


def dashboard_provider(session: Session, project_id: int, user_id: int | None, limits: dict) -> dict:
    return {
        "tasks_by_status": _counts(session, project_id),
        "chart": _chart(session, project_id, int(limits.get("chart_days") or 1)),
        "upcoming_deadlines": _upcoming(session, project_id, int(limits.get("upcoming_deadlines") or 1)),
    }


def search_provider(session: Session, project_id: int, user_id: int | None, query: str, limit: int) -> list[dict]:
    needle = query.casefold()
    rows = session.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.updated_at.desc())).all()
    found = []
    tags = _tags_by_task(session, [row.id for row in rows])
    for row in rows:
        hay = " ".join([row.title, row.description or "", " ".join(item["name"] for item in tags.get(row.id, []))])
        if needle in hay.casefold():
            found.append({"id": row.id, "title": row.title})
        if len(found) >= limit:
            break
    return found


def check_deadlines() -> None:
    from app.core.db import session_scope

    with session_scope() as session:
        rows = session.execute(
            select(Task, TaskStatus.is_closed)
            .join(TaskStatus, TaskStatus.id == Task.status_id)
            .where(Task.deadline.is_not(None), TaskStatus.is_closed.is_(False))
        ).all()
        zone = _zone()
        today = datetime.now(zone).date()
        for task, _closed in rows:
            due = task.deadline.astimezone(zone).date()
            days = (due - today).days
            if days < 0:
                key = "task:" + str(task.id) + ":overdue:" + today.isoformat()
                _notice(session, task, TASK_OVERDUE, key, days)
            elif days in _warn_days(task.project_id):
                key = "task:" + str(task.id) + ":deadline:" + due.isoformat() + ":" + str(days)
                _notice(session, task, TASK_DEADLINE_SOON, key, days)


def _notice(session: Session, task: Task, event_type: str, key: str, days: int) -> None:
    exists = session.scalars(select(TaskNotice.id).where(TaskNotice.dedup_key == key)).first()
    if exists is not None:
        return
    session.add(TaskNotice(dedup_key=key, task_id=task.id, event_type=event_type, created_at=utcnow()))
    payload = _event_payload(task)
    payload["days_left"] = days
    payload["dedup_key"] = key
    enqueue(session, event_type, payload, user_id=None)
    with log_scope("tasks", "deadline"):
        logger.info("deadline event type={} task={} days={}", event_type, task.id, days)


def _warn_days(project_id: int) -> set[int]:
    raw = get("tasks", "deadlines.warn_days", project_id=project_id)
    if not isinstance(raw, list):
        return set()
    return {item for item in raw if isinstance(item, int) and not isinstance(item, bool) and item >= 0}


def _counts(session: Session, project_id: int) -> list[dict]:
    rows = _statuses(session, project_id)
    counts = dict(
        session.execute(
            select(Task.status_id, func.count()).where(Task.project_id == project_id).group_by(Task.status_id)
        ).all()
    )
    return [
        {"status_id": row.id, "name": row.name, "color": row.color, "is_closed": row.is_closed, "count": int(counts.get(row.id, 0))}
        for row in rows
    ]


def _chart(session: Session, project_id: int, days: int) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    span = max(1, days)
    labels = []
    created = []
    closed = []
    rows = session.execute(
        select(Task.created_at, Task.closed_at).where(Task.project_id == project_id)
    ).all()
    from datetime import timedelta

    for offset in range(span - 1, -1, -1):
        day = today - timedelta(days=offset)
        labels.append(day.isoformat())
        created.append(sum(1 for item in rows if item[0] is not None and item[0].astimezone(zone).date() == day))
        closed.append(sum(1 for item in rows if item[1] is not None and item[1].astimezone(zone).date() == day))
    return {"labels": labels, "created": created, "closed": closed}


def _upcoming(session: Session, project_id: int, limit: int) -> list[dict]:
    rows = session.execute(
        select(Task)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(Task.project_id == project_id, Task.deadline.is_not(None), TaskStatus.is_closed.is_(False))
        .order_by(Task.deadline.asc(), Task.id.asc())
        .limit(max(1, limit))
    ).scalars().all()
    return [{"id": row.id, "title": row.title, "deadline": row.deadline.isoformat()} for row in rows]
