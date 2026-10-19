"""Провайдеры для дашборда/инбокса/поиска, пробы здоровья и джобы планировщика."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from app.core.db import session_scope
from app.core.events_catalog import MAIL_EVENT_SOON, MAIL_EVENT_TODAY
from app.core.settings_store import get_bool, get_int
from app.modules.mail import imap_client
from app.modules.mail.models import MailEvent, MailMessage
from app.modules.mail.service._matching import _row_matches
from app.modules.mail.service._queries import _all_accounts, _matching_messages, _rules
from app.modules.mail.service._serialize import _meta, _snippet, _title
from app.modules.mail.service._settings import _error_text, _timeout, _unpack, _zone
from app.modules.mail.service._threads import _grouped_messages
from app.modules.mail.service.ingest import _notify_event


def remind_events() -> None:
    if not get_bool("mail", "events.remind"):
        return
    warn_hours = get_int("mail", "events.warn_hours")
    grace = get_int("mail", "events.grace_minutes")
    with session_scope() as session:
        zone = _zone()
        now = datetime.now(zone)
        day_start = datetime(now.year, now.month, now.day, tzinfo=zone)
        day_end = day_start + timedelta(days=1)
        horizon = now + timedelta(hours=max(0, warn_hours))
        soon_from = now - timedelta(minutes=max(0, grace))
        window_end = horizon if horizon > day_end else day_end
        window_start = soon_from if soon_from < day_start else day_start
        rows = session.scalars(
            select(MailEvent).where(MailEvent.starts_at >= window_start, MailEvent.starts_at <= window_end)
        ).all()
        today_key = now.date().isoformat()
        for row in rows:
            start = row.starts_at.astimezone(zone)
            if start.date().isoformat() == today_key and (row.reminded_day or "") != today_key:
                row.reminded_day = today_key
                _notify_event(session, row, MAIL_EVENT_TODAY, "События из почты сегодня")
            if not row.reminded_soon and soon_from <= start <= horizon:
                row.reminded_soon = True
                _notify_event(session, row, MAIL_EVENT_SOON, "События из почты скоро")


def events_today(session: Session, user_id: int | None, limit: int, project_ids: list[int]) -> list[dict]:
    zone = _zone()
    now = datetime.now(zone)
    start = datetime(now.year, now.month, now.day, tzinfo=zone)
    end = start + timedelta(days=1)
    rows = session.scalars(
        select(MailEvent)
        .where(MailEvent.starts_at >= start, MailEvent.starts_at < end)
        .order_by(MailEvent.starts_at)
        .limit(max(1, limit))
    ).all()
    return [
        {
            "id": row.id,
            "message_id": row.message_id,
            "summary": row.summary,
            "location": row.location,
            "starts_at": row.starts_at.isoformat(),
            "ends_at": row.ends_at.isoformat() if row.ends_at else None,
        }
        for row in rows
    ]


def inbox_provider(session: Session, user_id: int | None, limit: int, project_ids: list[int]) -> list[dict]:
    scan = get_int("mail", "threads.scan_limit") if get_bool("mail", "threads.enabled") else max(1, limit)
    rows = list(
        session.scalars(
            select(MailMessage)
            .options(defer(MailMessage.html_body))
            .where(MailMessage.read.is_(False), MailMessage.archived.is_(False))
            .order_by(MailMessage.received_at.desc(), MailMessage.id.desc())
            .limit(max(1, scan))
        ).all()
    )
    if get_bool("mail", "threads.enabled"):
        grouped = _grouped_messages(session, rows, None)[: max(1, limit)]
        return [
            {
                "id": item["id"],
                "project_id": item["project_id"],
                "title": item["title"],
                "from_addr": item["from_addr"],
                "received_at": item["received_at"],
                "attachment_count": item["attachment_count"],
                "thread_count": item["thread_count"],
            }
            for item in grouped
        ]
    return [
        {
            "id": row.id,
            "project_id": row.project_id,
            "title": _title(row, row.project_id),
            "from_addr": row.from_addr,
            "received_at": row.received_at.isoformat(),
            "attachment_count": len(_meta(row)),
            "thread_count": 1,
        }
        for row in rows[: max(1, limit)]
    ]


def card_provider(session: Session, project_id: int, user_id: int | None) -> dict:
    rules = [rule for rule in _rules(session, project_id) if rule.enabled]
    if not rules:
        return {"new_mail": 0}
    rows = session.scalars(select(MailMessage).where(MailMessage.read.is_(False), MailMessage.archived.is_(False))).all()
    count = sum(1 for row in rows if _row_matches(rules, row, project_id))
    return {"new_mail": count}


def dashboard_provider(session: Session, project_id: int, user_id: int | None, limits: dict) -> dict:
    limit = int(limits.get("recent_mail") or 1)
    rows = _matching_messages(session, project_id, include_archived=False)
    if get_bool("mail", "threads.enabled", project_id=project_id):
        grouped = _grouped_messages(session, rows, project_id)
        return {
            "recent_mail": [
                {"id": item["id"], "title": item["title"], "thread_count": item["thread_count"]}
                for item in grouped[:limit]
            ]
        }
    return {"recent_mail": [{"id": row.id, "title": _title(row, project_id), "thread_count": 1} for row in rows[:limit]]}


def search_provider(session: Session, project_id: int, user_id: int | None, query: str, limit: int) -> list[dict]:
    needle = query.casefold()
    include_archived = get_bool("mail", "search.include_archived", project_id=project_id)
    rows = _matching_messages(session, project_id, include_archived=include_archived)
    width = get_int("mail", "search.snippet_chars", project_id=project_id)
    found = []
    for row in rows:
        blob = "\n".join([row.subject or "", row.from_name or "", row.from_addr or "", row.to_addr or "", row.body or ""])
        if needle in blob.casefold():
            found.append({"id": row.id, "title": _title(row, project_id), "snippet": _snippet(blob, needle, width)})
        if len(found) >= limit:
            break
    return found


def probe_accounts(session: Session, user_id: int | None) -> list[dict]:
    snaps = []
    for row in _all_accounts(session):
        snaps.append(
            {
                "id": row.id,
                "name": row.name,
                "blocked": bool(row.auth_blocked),
                "error": row.last_error or "",
                "host": row.host,
                "port": row.port,
                "ssl": row.use_ssl,
                "username": row.username,
                "folder": row.folder,
                "password": "" if row.auth_blocked else _unpack(row),
                "project_id": row.project_id,
            }
        )
    session.commit()
    items = []
    for snap in snaps:
        if snap["blocked"]:
            items.append({"id": str(snap["id"]), "label": snap["name"], "status": "warn", "detail": snap["error"] or "Пароль не подошёл"})
            continue
        if not snap["password"]:
            items.append({"id": str(snap["id"]), "label": snap["name"], "status": "warn", "detail": "Пароль не задан"})
            continue
        error = imap_client.check_login(
            snap["host"], snap["port"], snap["ssl"], snap["username"], snap["password"], snap["folder"], _timeout(snap["project_id"])
        )
        if error:
            items.append({"id": str(snap["id"]), "label": snap["name"], "status": "bad", "detail": _error_text(error, snap["password"])})
        else:
            items.append({"id": str(snap["id"]), "label": snap["name"], "status": "ok", "detail": "Вход прошёл"})
    if not items:
        items.append({"id": "none", "label": "Ящик", "status": "warn", "detail": "Ящиков нет"})
    return items


def probe_events(session: Session) -> dict:
    zone = _zone()
    now = datetime.now(zone)
    start = datetime(now.year, now.month, now.day, tzinfo=zone)
    end = start + timedelta(days=1)
    today = session.scalar(select(func.count()).select_from(MailEvent).where(MailEvent.starts_at >= start, MailEvent.starts_at < end)) or 0
    total = session.scalar(select(func.count()).select_from(MailEvent)) or 0
    return {"id": "mail-events", "label": "События из почты", "status": "ok", "detail": "Сегодня " + str(today) + ", всего " + str(total)}


def schedule_accounts() -> list[dict]:
    with session_scope() as session:
        rows = _all_accounts(session)
        return [{"id": row.id, "name": row.name, "enabled": bool(row.enabled), "blocked": bool(row.auth_blocked)} for row in rows]
