"""Сводка времени по всем проектам сразу (патч S).

Глобальный взгляд на неделю: сколько списано в каждом проекте и что именно
делалось — записи с задачами и заметками. Две недели рядом: текущая и
прошлая. Границы считает ``timetracking.week.starts_on`` (по умолчанию
0 — понедельник, то есть «с понедельника до воскресенья»).

Живёт в пакете сервиса, но не смешивается с проектной логикой: у сводки
нет ни одной общей строки с таймером, записями и отчётами проекта.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.settings_store import get_int, get_str
from app.modules.projects.models import Project
from app.modules.timetracking.models import TimeEntry
from app.modules.timetracking.service._shared import _live_minutes, _week_start, _zone


def overview(session: Session) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    current_start = _week_start(today)
    previous_start = current_start - timedelta(days=7)
    rows = list(
        session.scalars(
            select(TimeEntry).order_by(TimeEntry.started_at.desc(), TimeEntry.id.desc())
        ).all()
    )
    projects = {row.id: row for row in session.scalars(select(Project)).all()}
    current = _week_block(session, rows, current_start, current_start + timedelta(days=6), zone, projects)
    previous = _week_block(session, rows, previous_start, previous_start + timedelta(days=6), zone, projects)
    return {
        "week": {
            "starts_on": get_int("timetracking", "week.starts_on") % 7,
            "label": get_str("timetracking", "report.label.week"),
        },
        "current_week": current,
        "previous_week": previous,
    }


def _week_block(
    session: Session,
    rows: list[TimeEntry],
    start: date,
    end: date,
    zone,
    projects: dict[int, Project],
) -> dict:
    picked = [row for row in rows if start <= row.started_at.astimezone(zone).date() <= end]
    grouped: dict[int, list[TimeEntry]] = {}
    for row in picked:
        grouped.setdefault(row.project_id, []).append(row)
    blocks = []
    for project_id, entries in sorted(
        grouped.items(),
        key=lambda item: (-_minutes_of(item[1]), item[0]),
    ):
        project = projects.get(project_id)
        blocks.append(
            {
                "project_id": project_id,
                "project_name": project.name if project is not None else "",
                "project_archived": bool(project.archived) if project is not None else False,
                "minutes": _minutes_of(entries),
                "entries": [_entry_out(session, row, zone) for row in entries],
            }
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_minutes": _minutes_of(picked),
        "projects": blocks,
    }


def _entry_out(session: Session, row: TimeEntry, zone) -> dict:
    running = row.ended_at is None
    minutes = _live_minutes(row, utcnow()) if running else int(row.minutes or 0)
    title = ""
    if row.task_id:
        try:
            from app.modules.tasks.service import get_task

            title = get_task(session, row.project_id, row.task_id)["title"]
        except Exception:
            title = ""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "task_title": title,
        "note": row.note or "",
        "day": row.started_at.astimezone(zone).date().isoformat(),
        "started_at": row.started_at.isoformat(),
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "minutes": minutes,
        "running": running,
    }


def _minutes_of(rows: list[TimeEntry]) -> int:
    total = 0
    for row in rows:
        if row.ended_at is None:
            total += _live_minutes(row, utcnow())
        else:
            total += int(row.minutes or 0)
    return total
