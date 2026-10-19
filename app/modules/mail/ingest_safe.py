"""Безопасная вставка письма: гонка джобы и ручного fetch не роняет транзакцию."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.modules.mail.models import MailMessage


def add_message_safe(session: Session, row: MailMessage) -> MailMessage | None:
    """Добавляет письмо. При конфликте уникального (account_id, folder, uid) возвращает None."""
    try:
        session.add(row)
        session.flush()
        return row
    except IntegrityError:
        session.rollback()
        logger.info(
            "mail duplicate skipped account={} folder={} uid={}",
            row.account_id,
            row.folder,
            row.uid,
        )
        return None
