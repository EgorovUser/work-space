"""Страница «Учёт времени» проекта: лента записей и отчёт, карточка и дашборд."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import get_int, get_str
from app.modules.timetracking.models import TimeEntry
from app.modules.timetracking.service._shared import (
    _counted_minutes,
    _format_hours,
    _hours_number,
    _in_days,
    _live_minutes,
    _open_for_user,
    _out,
    _sum_rows,
    _titles,
    _week_start,
    _zone,
)


def project_time(session: Session, project_id: int, user_id: int, days: int | None) -> dict:
    span = _span(days, project_id)
    zone = _zone()
    today = datetime.now(zone).date()
    start = today - timedelta(days=span - 1)
    entries = _entries_between(session, project_id, start, today)
    titles = _titles(session, project_id, [row.task_id for row in entries])
    open_row = _open_for_user(session, user_id)
    running = None
    elsewhere = None
    if open_row is not None:
        payload = _out(session, open_row, titles if open_row.project_id == project_id else None)
        if open_row.project_id == project_id:
            running = payload
        else:
            elsewhere = payload
    return {
        "running": running,
        "running_elsewhere": elsewhere,
        "entries": [_out(session, row, titles) for row in entries],
        "report": _report(session, project_id, start, today, zone),
    }


def card_provider(session: Session, project_id: int, user_id: int | None) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    start = _week_start(today)
    minutes = _sum(session, project_id, start, today, zone)
    return {"hours_week": _hours_number(minutes, project_id)}


def dashboard_provider(session: Session, project_id: int, user_id: int | None, limits: dict) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    week = _week_start(today)
    today_minutes = _sum(session, project_id, today, today, zone)
    week_minutes = _sum(session, project_id, week, today, zone)
    rows = [
        {"name": get_str("timetracking", "report.label.today", project_id=project_id), "count": _format_hours(today_minutes, project_id)},
        {"name": get_str("timetracking", "report.label.week", project_id=project_id), "count": _format_hours(week_minutes, project_id)},
    ]
    running = session.scalars(
        select(TimeEntry).where(TimeEntry.project_id == project_id, TimeEntry.ended_at.is_(None)).limit(1)
    ).first()
    if running is not None:
        rows.append({
            "name": get_str("timetracking", "report.label.timer", project_id=project_id),
            "count": _format_hours(_live_minutes(running, _now()), project_id),
        })
    return {"hours": rows}


def _now():
    from app.core.db import utcnow

    return utcnow()


def _report(session: Session, project_id: int, start: date, today: date, zone) -> dict:
    rows = list(session.scalars(select(TimeEntry).where(TimeEntry.project_id == project_id)).all())
    labels = []
    hours = []
    day = start
    while day <= today:
        labels.append(day.isoformat())
        hours.append(_hours_number(_sum_rows(rows, day, day, zone), project_id))
        day += timedelta(days=1)
    grouped: dict[int | None, int] = {}
    for row in rows:
        if not _in_days(row, start, today, zone):
            continue
        grouped[row.task_id] = grouped.get(row.task_id, 0) + _counted_minutes(row)
    titles = _titles(session, project_id, list(grouped))
    blank = get_str("timetracking", "report.label.no_task", project_id=project_id)
    by_task = [
        {"task_id": task_id, "title": titles.get(task_id) or blank, "minutes": minutes}
        for task_id, minutes in sorted(grouped.items(), key=lambda item: (-item[1], item[0] or 0))
    ]
    return {
        "today_minutes": _sum_rows(rows, today, today, zone),
        "week_minutes": _sum_rows(rows, _week_start(today), today, zone),
        "chart": {"labels": labels, "hours": hours, "label": get_str("timetracking", "report.chart_label", project_id=project_id)},
        "by_task": by_task,
    }


def _entries_between(session: Session, project_id: int, start: date, end: date) -> list[TimeEntry]:
    zone = _zone()
    limit = get_int("timetracking", "list.limit", project_id=project_id)
    rows = list(
        session.scalars(
            select(TimeEntry).where(TimeEntry.project_id == project_id).order_by(TimeEntry.started_at.desc(), TimeEntry.id.desc())
        ).all()
    )
    picked = [row for row in rows if _in_days(row, start, end, zone)]
    return picked[:limit]


def _sum(session: Session, project_id: int, start: date, end: date, zone) -> int:
    rows = list(session.scalars(select(TimeEntry).where(TimeEntry.project_id == project_id)).all())
    return _sum_rows(rows, start, end, zone)


def _span(days: int | None, project_id: int) -> int:
    maximum = get_int("timetracking", "report.days_max")
    if days is None:
        days = get_int("timetracking", "report.chart_days", project_id=project_id)
    if days < 1:
        raise HTTPException(status_code=400, detail="Слишком короткий период")
    return min(days, maximum)
