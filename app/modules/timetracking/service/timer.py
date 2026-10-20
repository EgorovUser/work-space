"""Таймер: старт, стоп, автостоп просроченных джобой."""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import session_scope, utcnow
from app.core.events_catalog import TIME_STARTED, TIME_STOPPED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int
from app.modules.projects.service import touch_project
from app.modules.timetracking.models import TimeEntry
from app.modules.timetracking.service._shared import _live_minutes, _note, _open_for_user, _out, _task
from app.modules.timetracking.service.entries import _normalize


def start_timer(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    stopped = None
    open_row = _open_for_user(session, user_id)
    if open_row is not None:
        if not get_bool("timetracking", "timer.autostop", project_id=project_id):
            raise HTTPException(status_code=409, detail="Таймер уже запущен")
        _close(session, open_row, utcnow(), clamp=True)
        touch_project(session, open_row.project_id)
        session.flush()
        stopped = open_row.id
    now = utcnow()
    row = TimeEntry(
        project_id=project_id,
        user_id=user_id,
        task_id=_task(session, project_id, fields.get("task_id")),
        note=_note(fields.get("note") or ""),
        started_at=now,
        ended_at=None,
        minutes=0,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Таймер уже запущен") from exc
    touch_project(session, project_id)
    with log_scope("timetracking", "start", user_id=user_id):
        logger.info("timer start id={} stopped={}", row.id, stopped)
    enqueue(
        session,
        TIME_STARTED,
        {"title": "Таймер запущен", "project_id": project_id, "link": "/projects/" + str(project_id) + "/time"},
        user_id=user_id,
    )
    return {"entry": _out(session, row), "stopped_id": stopped}


def stop_timer(session: Session, project_id: int, user_id: int) -> dict:
    row = _open_for_user(session, user_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Таймер не запущен")
    _close(session, row, utcnow(), clamp=True)
    touch_project(session, project_id)
    session.flush()
    with log_scope("timetracking", "stop", user_id=user_id):
        logger.info("timer stop id={} minutes={}", row.id, row.minutes)
    enqueue(
        session,
        TIME_STOPPED,
        {"title": "Таймер остановлен", "subject": str(row.minutes) + " мин", "project_id": project_id, "link": "/projects/" + str(project_id) + "/time"},
        user_id=user_id,
    )
    return _out(session, row)


def autostop_open() -> None:
    if not get_bool("timetracking", "timer.job_enabled"):
        return
    now = utcnow()
    with session_scope() as session:
        rows = list(session.scalars(select(TimeEntry).where(TimeEntry.ended_at.is_(None))).all())
        stopped = 0
        for row in rows:
            limit = get_int("timetracking", "timer.max_open_minutes", project_id=row.project_id)
            if _live_minutes(row, now) < limit:
                continue
            row.ended_at = row.started_at + timedelta(minutes=limit)
            row.minutes = _normalize(limit, row.project_id, clamp=True)
            row.updated_at = now
            touch_project(session, row.project_id)
            stopped += 1
            logger.info("timer autostop id={} minutes={}", row.id, row.minutes)
        if stopped:
            session.flush()


def _close(session: Session, row: TimeEntry, now, clamp: bool) -> None:
    from app.modules.timetracking.service.entries import _minutes_between

    row.ended_at = now
    row.minutes = _minutes_between(row.started_at, now, row.project_id, clamp=clamp)
    if clamp:
        limit = get_int("timetracking", "timer.max_open_minutes", project_id=row.project_id)
        if row.minutes > limit:
            row.minutes = _normalize(limit, row.project_id, clamp=True)
            row.ended_at = row.started_at + timedelta(minutes=row.minutes)
    row.updated_at = now
