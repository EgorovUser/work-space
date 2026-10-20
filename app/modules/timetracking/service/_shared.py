"""Общие хелперы сервиса учёта времени: даты, зона, сериализация записей.

Ничего публичного: файл существует, чтобы таймер, записи и отчёты не
тащили одни и те же функции друг у друга.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.settings_store import get_int, get_str
from app.modules.timetracking.models import TimeEntry


def _zone():
    name = get_str("core", "ui.timezone")
    if not name:
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except Exception:
        return datetime.now().astimezone().tzinfo


def _week_start(today: date) -> date:
    first = get_int("timetracking", "week.starts_on") % 7
    return today - timedelta(days=(today.weekday() - first) % 7)


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Не разобрали дату") from exc


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Не разобрали дату") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_zone())
    return parsed.astimezone(timezone.utc)


def _note(value: str) -> str:
    text = (value or "").strip()
    limit = get_int("timetracking", "note.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Заметка длиннее " + str(limit) + " символов")
    return text


def _task(session: Session, project_id: int, task_id) -> int | None:
    if task_id in (None, "", 0):
        return None
    try:
        task_id = int(task_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Задача не найдена") from exc
    from app.modules.tasks.service import get_task

    get_task(session, project_id, task_id)
    return task_id


def _titles(session: Session, project_id: int, task_ids: list) -> dict:
    found: dict = {}
    for task_id in task_ids:
        if not task_id or task_id in found:
            continue
        try:
            from app.modules.tasks.service import get_task

            found[task_id] = get_task(session, project_id, task_id)["title"]
        except Exception:
            found[task_id] = ""
    return found


def _entry(session: Session, project_id: int, entry_id: int) -> TimeEntry:
    row = session.get(TimeEntry, entry_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return row


def _open_for_user(session: Session, user_id: int) -> TimeEntry | None:
    return session.scalars(
        select(TimeEntry).where(TimeEntry.user_id == user_id, TimeEntry.ended_at.is_(None))
    ).first()


def _live_minutes(row: TimeEntry, now: datetime) -> int:
    seconds = (now - row.started_at).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)


def _counted_minutes(row: TimeEntry) -> int:
    if row.ended_at is None:
        return _live_minutes(row, utcnow())
    return int(row.minutes or 0)


def _in_days(row: TimeEntry, start: date, end: date, zone) -> bool:
    local = row.started_at.astimezone(zone).date()
    return start <= local <= end


def _sum_rows(rows: list[TimeEntry], start: date, end: date, zone) -> int:
    total = 0
    for row in rows:
        if _in_days(row, start, end, zone):
            total += _counted_minutes(row)
    return total


def _hours_number(minutes: int, project_id: int) -> float:
    decimals = get_int("timetracking", "report.decimals", project_id=project_id)
    return round((minutes or 0) / 60, decimals)


def _format_hours(minutes: int, project_id: int) -> str:
    decimals = get_int("timetracking", "report.decimals", project_id=project_id)
    number = _hours_number(minutes, project_id)
    unit = get_str("timetracking", "report.unit", project_id=project_id).strip()
    text = f"{number:.{decimals}f}"
    return (text + " " + unit).strip()


def _out(session: Session, row: TimeEntry, titles: dict | None = None) -> dict:
    if titles is None:
        titles = _titles(session, row.project_id, [row.task_id])
    running = row.ended_at is None
    return {
        "id": row.id,
        "project_id": row.project_id,
        "user_id": row.user_id,
        "task_id": row.task_id,
        "task_title": titles.get(row.task_id, ""),
        "note": row.note or "",
        "started_at": row.started_at.isoformat(),
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "minutes": _live_minutes(row, utcnow()) if running else int(row.minutes or 0),
        "running": running,
    }
