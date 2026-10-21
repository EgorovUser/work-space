"""Лента уведомлений: списки, непрочитанные, отметки о прочтении, мета, пробы."""

from __future__ import annotations

import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.logging import log_scope, logger
from app.core.settings_store import get_int
from app.modules.notifications import channels
from app.modules.notifications.models import Notification
from app.modules.notifications.service._bus import publish_event
from app.modules.notifications.service._queries import _own, _unread_count
from app.modules.notifications.service._serialize import _out
from app.modules.notifications.service._settings import _choices, _matrix


def list_notifications(session: Session, user_id: int, unread_only: bool) -> dict:
    limit = get_int("notifications", "list.limit", user_id=user_id)
    statement = select(Notification).where(Notification.user_id == user_id, Notification.show_browser.is_(True))
    if unread_only:
        statement = statement.where(Notification.read.is_(False))
    rows = session.scalars(statement.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)).all()
    return {"items": [_out(session, row, user_id) for row in rows], "unread": _unread_count(session, user_id)}


def home_items(session: Session, user_id: int | None) -> list[dict]:
    """Лента уведомлений для хаба «Сегодня».

    Облегчённый вариант ``_out``: без доставок (и их N+1) — только то, что
    нужно для строки на главной. Провайдер регистрируется на мосту как блок
    домашнего экрана и вызывается из проектов, поэтому сигнатура общая.
    """
    if user_id is None:
        return []
    limit = get_int("notifications", "home.limit", user_id=user_id)
    rows = session.scalars(
        select(Notification)
        .where(Notification.user_id == user_id, Notification.show_browser.is_(True))
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(max(1, limit))
    ).all()
    return [
        {
            "id": row.id,
            "event_type": row.event_type,
            "title": row.title,
            "body": row.body or "",
            "link": row.link or "",
            "read": bool(row.read),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def unread(session: Session, user_id: int) -> dict:
    limit = get_int("notifications", "bell.limit", user_id=user_id)
    rows = session.scalars(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.show_browser.is_(True),
            Notification.read.is_(False),
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    ).all()
    return {"count": _unread_count(session, user_id), "items": [_out(session, row, user_id) for row in rows]}


def mark_read(session: Session, user_id: int, notification_id: int) -> dict:
    return _retry_write(session, lambda: _mark_read(session, user_id, notification_id))


def mark_all_read(session: Session, user_id: int) -> dict:
    return _retry_write(session, lambda: _mark_all_read(session, user_id))


def probe(user_id: int, channel: str) -> dict:
    item = channels.channel_def(channel)
    if item is None:
        raise HTTPException(status_code=400, detail="Неизвестный канал")
    if not item.server_delivery or item.tester is None:
        raise HTTPException(status_code=400, detail="У канала нет серверской отправки")
    status, error = item.tester(user_id)
    if status != "sent":
        raise HTTPException(status_code=400, detail=error or "Не отправилось")
    with log_scope("notifications", "probe", user_id=user_id):
        logger.info("probe sent channel={}", channel)
    return {"ok": True}


def meta(user_id: int) -> dict:
    return {
        "events": _choices("events"),
        "channels": _choices("channels"),
        "statuses": _choices("statuses"),
        "matrix": _matrix(user_id),
    }


def _mark_read(session: Session, user_id: int, notification_id: int) -> dict:
    row = _own(session, user_id, notification_id)
    row.read = True
    session.flush()
    publish_event("notifications.changed", user_id=user_id)
    with log_scope("notifications", "read", user_id=user_id):
        logger.info("notification read id={}", notification_id)
    return _out(session, row, user_id)


def _mark_all_read(session: Session, user_id: int) -> dict:
    rows = session.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.show_browser.is_(True),
            Notification.read.is_(False),
        )
    ).all()
    for row in rows:
        row.read = True
    session.flush()
    publish_event("notifications.changed", user_id=user_id)
    with log_scope("notifications", "read", user_id=user_id):
        logger.info("notifications read all count={}", len(rows))
    return {"updated": len(rows)}


def _retry_write(session: Session, action):
    last = None
    for attempt in range(3):
        try:
            result = action()
            session.commit()
            return result
        except OperationalError as exc:
            last = exc
            session.rollback()
            time.sleep(0.3 * (attempt + 1))
    raise HTTPException(status_code=503, detail="База занята записью почты, повторите") from last
