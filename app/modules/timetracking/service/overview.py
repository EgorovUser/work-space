"""Сводка времени по всем проектам сразу (патч S; производительность — AB).

Глобальный взгляд на неделю: сколько списано в каждом проекте и что именно
делалось — записи с задачами и заметками. Две недели рядом: текущая и
прошлая. Границы считает ``timetracking.week.starts_on`` (по умолчанию
0 — понедельник, то есть «с понедельника до воскресенья»).

Одна сводка — три запроса, сколько бы ни было записей и проектов:

- записи двух недель одним SELECT с фильтром по интервалу (UTC-границы
  считаются от часового пояса настроек — локальный день записи и есть
  её день недели);
- проекты одним SELECT;
- заголовки задач одним батчем ``IN`` — раньше заголовок тянулся
  отдельным запросом на каждую запись с задачей (N+1).

Живёт в пакете сервиса, но не смешивается с проектной логикой: у сводки
нет ни одной общей строки с таймером, записями и отчётами проекта.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

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
    # Границы интервала — в UTC: started_at хранится в UTC, а локальный
    # день записи определяется её timestamp в поясе настроек. Запись,
    # начатая в понедельник 00:30 по местному, лежит в интервале.
    span_start = datetime.combine(previous_start, time(0), tzinfo=zone).astimezone(timezone.utc)
    span_end = datetime.combine(current_start + timedelta(days=7), time(0), tzinfo=zone).astimezone(timezone.utc)
    rows = list(
        session.scalars(
            select(TimeEntry)
            .where(TimeEntry.started_at >= span_start, TimeEntry.started_at < span_end)
            .order_by(TimeEntry.started_at.desc(), TimeEntry.id.desc())
        ).all()
    )
    projects = {row.id: row for row in session.scalars(select(Project)).all()}
    titles = _task_titles(session, rows)
    current = _week_block(rows, current_start, current_start + timedelta(days=6), zone, projects, titles)
    previous = _week_block(rows, previous_start, previous_start + timedelta(days=6), zone, projects, titles)
    return {
        "week": {
            "starts_on": get_int("timetracking", "week.starts_on") % 7,
            "label": get_str("timetracking", "report.label.week"),
        },
        "current_week": current,
        "previous_week": previous,
    }


def _task_titles(session: Session, rows: list[TimeEntry]) -> dict[int, str]:
    """Заголовки задач одним батчем: IN вместо запроса на каждую запись."""
    ids = sorted({row.task_id for row in rows if row.task_id})
    if not ids:
        return {}
    from app.modules.tasks.models import Task

    found = session.execute(select(Task.id, Task.title).where(Task.id.in_(ids))).all()
    return {int(task_id): title or "" for task_id, title in found}


def _week_block(
    rows: list[TimeEntry],
    start: date,
    end: date,
    zone,
    projects: dict[int, Project],
    titles: dict[int, str],
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
                "entries": [_entry_out(row, zone, titles) for row in entries],
            }
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_minutes": _minutes_of(picked),
        "projects": blocks,
    }


def _entry_out(row: TimeEntry, zone, titles: dict[int, str]) -> dict:
    running = row.ended_at is None
    minutes = _live_minutes(row, utcnow()) if running else int(row.minutes or 0)
    return {
        "id": row.id,
        "task_id": row.task_id,
        "task_title": titles.get(row.task_id, "") if row.task_id else "",
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
