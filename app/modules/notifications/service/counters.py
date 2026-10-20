"""Счётчики для навигации (патч AA): непрочитанные уведомления.

Провайдер для хаба ``app/core/counters.py``: число показываемых
в браузере непрочитанных — то же, что раньше считал колокольчик и SSE.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.notifications.models import Notification


def global_counts(session: Session, user_id: int) -> dict:
    value = session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.show_browser.is_(True),
            Notification.read.is_(False),
        )
    )
    return {"notifications_unread": int(value or 0)}
