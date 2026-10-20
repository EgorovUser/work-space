"""Приватные выборки уведомлений: своё уведомление, счётчик непрочитанных, дедуп."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.notifications.models import Notification


def _own(session: Session, user_id: int, notification_id: int) -> Notification:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user_id or not row.show_browser:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    return row


def _unread_count(session: Session, user_id: int) -> int:
    value = session.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id,
            Notification.show_browser.is_(True),
            Notification.read.is_(False),
        )
    )
    return int(value or 0)


def _dedup_exists(session: Session, user_id: int, dedup: str) -> bool:
    found = session.scalars(
        select(Notification.id).where(Notification.user_id == user_id, Notification.dedup_key == dedup)
    ).first()
    return found is not None
