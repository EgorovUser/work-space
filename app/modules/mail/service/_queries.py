"""Приватные выборки строк: ящики, правила, письма, отбор под правила проекта."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import get_int
from app.modules.mail.models import MailAccount, MailMessage, MailRule
from app.modules.mail.service._matching import _row_matches


def _all_accounts(session: Session) -> list[MailAccount]:
    return list(session.scalars(select(MailAccount).order_by(MailAccount.id)).all())


def _accounts(session: Session, project_id: int) -> list[MailAccount]:
    return list(session.scalars(select(MailAccount).where(MailAccount.project_id == project_id).order_by(MailAccount.id)).all())


def _rules(session: Session, project_id: int) -> list[MailRule]:
    return list(session.scalars(select(MailRule).where(MailRule.project_id == project_id).order_by(MailRule.position, MailRule.id)).all())


def _account_any(session: Session, account_id: int) -> MailAccount:
    row = session.get(MailAccount, account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ящик не найден")
    return row


def _account(session: Session, project_id: int, account_id: int) -> MailAccount:
    row = session.get(MailAccount, account_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ящик не найден")
    return row


def _rule(session: Session, project_id: int, rule_id: int) -> MailRule:
    row = session.get(MailRule, rule_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    return row


def _message(session: Session, project_id: int, message_id: int) -> MailMessage:
    row = session.get(MailMessage, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    if not project_id:
        return row
    rules = [rule for rule in _rules(session, project_id) if rule.enabled]
    if _row_matches(rules, row, project_id):
        return row
    raise HTTPException(status_code=404, detail="Письмо не найдено")


def _matching_messages(session: Session, project_id: int, include_archived: bool) -> list[MailMessage]:
    statement = select(MailMessage)
    if not include_archived:
        statement = statement.where(MailMessage.archived.is_(False))
    scan = get_int("mail", "list.scan_limit", project_id=project_id)
    rows = list(session.scalars(statement.order_by(MailMessage.received_at.desc(), MailMessage.id.desc()).limit(scan)).all())
    rules = [rule for rule in _rules(session, project_id) if rule.enabled]
    return [row for row in rows if _row_matches(rules, row, project_id)]
