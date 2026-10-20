"""Повторяющиеся задачи: расчёт следующего вхождения и его создание.

Правило живёт на самой задаче (``repeat_kind`` / ``repeat_interval`` /
``repeat_until``). Следующее вхождение создаётся в момент закрытия задачи —
перенесли в закрытую колонку или сняли «выполнено»: серия продолжается,
закрытая карточка остаётся историей. Просроченные серии «догоняются»:
вхождение всегда получается в будущем.

Месяцы и годы идут по календарю: 31 января + 1 месяц = 28 февраля,
29 февраля + 1 год = 28 февраля. Локальное время суток сохраняется.
"""

from __future__ import annotations

import calendar as _calendar
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_catalog import TASK_RECURRED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.modules.projects.service import touch_project
from app.modules.tasks import events
from app.modules.tasks.models import ChecklistItem, Task, TaskTag
from app.modules.tasks.service._queries import _checks, _next_position, _pick_status
from app.modules.tasks.service._validators import _zone

KINDS = ("daily", "weekly", "monthly", "yearly")

# Сколько шагов «догоняния» допустимо: закрываем задачу, пролежавшую годы.
_CATCH_UP_STEPS = 5000


def advance(base: datetime, kind: str, interval: int) -> datetime:
    """Сдвигает момент на один шаг повтора, сохраняя локальное время."""
    zone = _zone()
    local = base.astimezone(zone)
    if kind == "daily":
        local = local + timedelta(days=interval)
    elif kind == "weekly":
        local = local + timedelta(weeks=interval)
    elif kind == "monthly":
        month = local.month - 1 + interval
        year = local.year + month // 12
        month = month % 12 + 1
        local = local.replace(year=year, month=month, day=min(local.day, _calendar.monthrange(year, month)[1]))
    elif kind == "yearly":
        day = 28 if (local.month == 2 and local.day == 29) else local.day
        local = local.replace(year=local.year + interval, day=day)
    else:
        raise ValueError("неизвестный тип повтора: " + str(kind))
    return local.astimezone(timezone.utc)


def next_deadline(task: Task, now: datetime | None = None) -> datetime | None:
    """Следующий срок серии: минимум на шаг вперёд и в будущем.

    ``None`` — задача не повторяется или серия закончилась (срок вышел за
    ``repeat_until``; граница сравнивается по календарным дням и входит в
    серию включительно).
    """
    if task.repeat_kind not in KINDS:
        return None
    moment = now or utcnow()
    base = task.deadline or moment
    # База из глубокой древности: не мотаем тысячи дней пошагово.
    if base < moment - timedelta(days=3650):
        base = moment
    due = advance(base, task.repeat_kind, task.repeat_interval)
    steps = 0
    while due <= moment and steps < _CATCH_UP_STEPS:
        due = advance(due, task.repeat_kind, task.repeat_interval)
        steps += 1
    if steps >= _CATCH_UP_STEPS:
        return None
    if task.repeat_until is not None:
        zone = _zone()
        if due.astimezone(zone).date() > task.repeat_until.astimezone(zone).date():
            return None
    return due


def spawn_next(session: Session, project_id: int, user_id: int | None, task: Task) -> Task | None:
    """Создаёт следующее вхождение серии. Возвращает его или ``None``.

    Копируются название, описание, исполнитель, приоритет, режим прогресса,
    метки и чеклист (сброшенный в «не выполнено»), правило повтора и граница
    серии. Новая карточка попадает в первую открытую колонку.
    """
    if task.repeat_kind not in KINDS:
        return None
    due = next_deadline(task)
    if due is None:
        return None
    status = _pick_status(session, project_id, None)
    fresh = Task(
        project_id=project_id,
        status_id=status.id,
        title=task.title,
        description=task.description or "",
        assignee_id=task.assignee_id,
        priority=task.priority,
        progress_mode=task.progress_mode,
        progress_manual=0,
        deadline=due,
        repeat_kind=task.repeat_kind,
        repeat_interval=task.repeat_interval,
        repeat_until=task.repeat_until,
        position=_next_position(session, status.id),
        created_by=user_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(fresh)
    session.flush()
    _copy_checklist(session, task.id, fresh.id)
    _copy_tags(session, task.id, fresh.id)
    when_local = due.astimezone(_zone()).strftime("%d.%m.%Y")
    events.add_event(session, fresh.id, user_id, events.CREATED, "Повторение задачи " + str(task.id))
    events.add_event(session, task.id, user_id, events.RECUR, "Вхождение на " + when_local)
    enqueue(
        session,
        TASK_RECURRED,
        {
            "title": "Повтор задачи",
            "subject": task.title,
            "project_id": project_id,
            "task_id": fresh.id,
            "link": "/projects/" + str(project_id) + "/tasks/" + str(fresh.id),
        },
        user_id=user_id,
    )
    touch_project(session, project_id)
    session.flush()
    with log_scope("tasks", "recur", user_id=user_id):
        logger.info("task recurred source={} fresh={} due={}", task.id, fresh.id, when_local)
    return fresh


def _copy_checklist(session: Session, source_id: int, target_id: int) -> None:
    for row in _checks(session, source_id):
        session.add(ChecklistItem(task_id=target_id, title=row.title, done=False, position=row.position))


def _copy_tags(session: Session, source_id: int, target_id: int) -> None:
    for link in session.scalars(select(TaskTag).where(TaskTag.task_id == source_id)).all():
        session.add(TaskTag(task_id=target_id, tag_id=link.tag_id))
