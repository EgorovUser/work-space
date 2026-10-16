from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import session_scope, utcnow
from app.core.events_catalog import TIME_CREATED, TIME_DELETED, TIME_STARTED, TIME_STOPPED, TIME_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int, get_str
from app.modules.projects.service import touch_project
from app.modules.timetracking.models import TimeEntry


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


def card_provider(session: Session, project_id: int, user_id: int | None) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    start = _week_start(today, project_id)
    minutes = _sum(session, project_id, start, today, zone)
    return {"hours_week": _hours_number(minutes, project_id)}


def dashboard_provider(session: Session, project_id: int, user_id: int | None, limits: dict) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    week = _week_start(today, project_id)
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
            "count": _format_hours(_live_minutes(running, utcnow()), project_id),
        })
    return {"hours": rows}


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
        "week_minutes": _sum_rows(rows, _week_start(today, project_id), today, zone),
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


def _close(session: Session, row: TimeEntry, now: datetime, clamp: bool) -> None:
    row.ended_at = now
    row.minutes = _minutes_between(row.started_at, now, row.project_id, clamp=clamp)
    if clamp:
        limit = get_int("timetracking", "timer.max_open_minutes", project_id=row.project_id)
        if row.minutes > limit:
            row.minutes = _normalize(limit, row.project_id, clamp=True)
            row.ended_at = row.started_at + timedelta(minutes=row.minutes)
    row.updated_at = now


def _manual_span(fields: dict, project_id: int) -> tuple[datetime, datetime, int]:
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
        day = _parse_day(day_raw) if day_raw else datetime.now(_zone()).date()
        hour = get_int("timetracking", "manual.day_start_hour", project_id=project_id)
        start = datetime.combine(day, time(hour=hour), tzinfo=_zone()).astimezone(timezone.utc)
    return start, start + timedelta(minutes=minutes), minutes


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


def _sum(session: Session, project_id: int, start: date, end: date, zone) -> int:
    rows = list(session.scalars(select(TimeEntry).where(TimeEntry.project_id == project_id)).all())
    return _sum_rows(rows, start, end, zone)


def _sum_rows(rows: list[TimeEntry], start: date, end: date, zone) -> int:
    total = 0
    for row in rows:
        if _in_days(row, start, end, zone):
            total += _counted_minutes(row)
    return total


def _counted_minutes(row: TimeEntry) -> int:
    if row.ended_at is None:
        return _live_minutes(row, utcnow())
    return int(row.minutes or 0)


def _in_days(row: TimeEntry, start: date, end: date, zone) -> bool:
    local = row.started_at.astimezone(zone).date()
    return start <= local <= end


def _live_minutes(row: TimeEntry, now: datetime) -> int:
    seconds = (now - row.started_at).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60)


def _hours_number(minutes: int, project_id: int) -> float:
    decimals = get_int("timetracking", "report.decimals", project_id=project_id)
    return round((minutes or 0) / 60, decimals)


def _format_hours(minutes: int, project_id: int) -> str:
    decimals = get_int("timetracking", "report.decimals", project_id=project_id)
    number = _hours_number(minutes, project_id)
    unit = get_str("timetracking", "report.unit", project_id=project_id).strip()
    text = f"{number:.{decimals}f}"
    return (text + " " + unit).strip()


def _week_start(today: date, project_id: int) -> date:
    first = get_int("timetracking", "week.starts_on", project_id=project_id) % 7
    return today - timedelta(days=(today.weekday() - first) % 7)


def _span(days: int | None, project_id: int) -> int:
    maximum = get_int("timetracking", "report.days_max")
    if days is None:
        days = get_int("timetracking", "report.chart_days", project_id=project_id)
    if days < 1:
        raise HTTPException(status_code=400, detail="Слишком короткий период")
    return min(days, maximum)


def _entry(session: Session, project_id: int, entry_id: int) -> TimeEntry:
    row = session.get(TimeEntry, entry_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return row


def _open_for_user(session: Session, user_id: int) -> TimeEntry | None:
    return session.scalars(
        select(TimeEntry).where(TimeEntry.user_id == user_id, TimeEntry.ended_at.is_(None))
    ).first()


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


def _note(value: str) -> str:
    text = (value or "").strip()
    limit = get_int("timetracking", "note.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Заметка длиннее " + str(limit) + " символов")
    return text


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


def _zone():
    name = get_str("core", "ui.timezone")
    if not name:
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except Exception:
        return datetime.now().astimezone().tzinfo
