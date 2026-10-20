"""Ручные записи времени: создание, правка, удаление."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_catalog import TIME_CREATED, TIME_DELETED, TIME_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_int
from app.modules.projects.service import touch_project
from app.modules.timetracking.models import TimeEntry
from app.modules.timetracking.service._shared import (
    _entry,
    _note,
    _out,
    _parse_day,
    _parse_dt,
    _task,
    _zone,
)


def create_entry(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    start, end, minutes = _manual_span(fields, project_id)
    now = utcnow()
    row = TimeEntry(
        project_id=project_id,
        user_id=user_id,
        task_id=_task(session, project_id, fields.get("task_id")),
        note=_note(fields.get("note") or ""),
        started_at=start,
        ended_at=end,
        minutes=minutes,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    enqueue(
        session,
        TIME_CREATED,
        {"title": "Запись времени", "subject": str(row.minutes) + " мин", "project_id": project_id, "link": "/projects/" + str(project_id) + "/time"},
        user_id=user_id,
    )
    with log_scope("timetracking", "create", user_id=user_id):
        logger.info("time entry id={} minutes={}", row.id, row.minutes)
    return _out(session, row)


def update_entry(session: Session, project_id: int, user_id: int, entry_id: int, fields: dict) -> dict:
    row = _entry(session, project_id, entry_id)
    if "note" in fields and fields["note"] is not None:
        row.note = _note(fields["note"])
    if "task_id" in fields:
        row.task_id = _task(session, project_id, fields.get("task_id"))
    if "started_at" in fields and fields["started_at"] is not None:
        row.started_at = _parse_dt(fields["started_at"])
    if row.ended_at is None and fields.get("minutes") not in (None, "") and "minutes" in fields:
        raise HTTPException(status_code=400, detail="Сначала остановите таймер")
    if "ended_at" in fields and fields["ended_at"] is not None:
        row.ended_at = _parse_dt(fields["ended_at"])
    if "minutes" in fields and fields["minutes"] is not None and row.ended_at is not None:
        row.minutes = _normalize(int(fields["minutes"]), project_id, clamp=False)
        row.ended_at = row.started_at + timedelta(minutes=row.minutes)
    elif row.ended_at is not None:
        row.minutes = _minutes_between(row.started_at, row.ended_at, project_id, clamp=False)
    if row.ended_at is not None and row.ended_at < row.started_at:
        raise HTTPException(status_code=400, detail="Конец раньше начала")
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        TIME_UPDATED,
        {"title": "Запись времени", "subject": str(row.minutes) + " мин", "project_id": project_id, "link": "/projects/" + str(project_id) + "/time"},
        user_id=user_id,
    )
    with log_scope("timetracking", "update", user_id=user_id):
        logger.info("time entry updated id={} minutes={}", row.id, row.minutes)
    return _out(session, row)


def delete_entry(session: Session, project_id: int, user_id: int, entry_id: int) -> None:
    row = _entry(session, project_id, entry_id)
    session.delete(row)
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        TIME_DELETED,
        {"title": "Запись времени удалена", "subject": str(row.minutes) + " мин", "project_id": project_id, "link": "/projects/" + str(project_id) + "/time"},
        user_id=user_id,
    )
    with log_scope("timetracking", "delete", user_id=user_id):
        logger.info("time entry deleted id={}", entry_id)


def _manual_span(fields: dict, project_id: int) -> tuple[datetime, datetime, int]:
    from datetime import time as dt_time

    started_raw = fields.get("started_at")
    ended_raw = fields.get("ended_at")
    minutes_raw = fields.get("minutes")
    day_raw = fields.get("day")
    if started_raw and ended_raw:
        start = _parse_dt(started_raw)
        end = _parse_dt(ended_raw)
        minutes = _minutes_between(start, end, project_id, clamp=False)
        return start, end, minutes
    if minutes_raw is None:
        raise HTTPException(status_code=400, detail="Укажите минуты или начало и конец")
    minutes = _normalize(int(minutes_raw), project_id, clamp=False)
    if started_raw:
        start = _parse_dt(started_raw)
    else:
        day = _parse_day(day_raw) if day_raw else _now_date()
        hour = get_int("timetracking", "manual.day_start_hour", project_id=project_id)
        start = datetime.combine(day, dt_time(hour=hour), tzinfo=_zone())
    return start, start + timedelta(minutes=minutes), minutes


def _now_date():
    from datetime import datetime

    return datetime.now(_zone()).date()


def _minutes_between(start: datetime, end: datetime, project_id: int, clamp: bool) -> int:
    seconds = (end - start).total_seconds()
    if seconds < 0:
        raise HTTPException(status_code=400, detail="Конец раньше начала")
    raw = math.ceil(seconds / 60) if seconds else 0
    return _normalize(raw, project_id, clamp=clamp)


def _normalize(raw: int, project_id: int, clamp: bool) -> int:
    if raw < 0:
        raise HTTPException(status_code=400, detail="Минуты не могут быть отрицательными")
    step = get_int("timetracking", "entry.round_to_minutes", project_id=project_id)
    minimum = get_int("timetracking", "entry.min_minutes", project_id=project_id)
    maximum = get_int("timetracking", "entry.max_minutes", project_id=project_id)
    minutes = raw
    if step > 1 and minutes:
        minutes = math.ceil(minutes / step) * step
    if minutes < minimum:
        minutes = minimum
    if minutes > maximum:
        if clamp:
            return maximum
        raise HTTPException(status_code=400, detail="Дольше " + str(maximum) + " минут")
    return int(minutes)
