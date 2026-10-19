"""Письма: общий ящик, ящик проекта, карточка письма, CRUD, импорт файла."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.core.events_catalog import MAIL_ARCHIVED, MAIL_DELETED
from app.core.files import add_link, save_bytes
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int
from app.modules.mail import imap_client, parse
from app.modules.mail.models import (
    MailAccount,
    MailAttachment,
    MailMessage,
    MailTag,
    MailTagHide,
    MailTagPin,
)
from app.modules.mail.service._matching import _row_matches
from app.modules.mail.service._queries import _accounts, _all_accounts, _message, _rules
from app.modules.mail.service._serialize import (
    _account_out,
    _message_out,
    _rule_out,
    _search_blob,
    _sync_info,
    _title,
)
from app.modules.mail.service._settings import _choices, _error_text, _limits, _timeout, _unpack
from app.modules.mail.service._tags import _attach_tags, tag_page
from app.modules.mail.service._threads import _grouped_messages, _thread_out
from app.modules.mail.service.accounts import _run_moves
from app.modules.mail.service.ingest import _ingest
from app.modules.mail.service.notify import notify_state


def mailbox(session: Session, unread_only: bool, include_archived: bool, query: str, tag_id: int = 0) -> dict:
    messages = _message_list(session, None, unread_only, include_archived, query)
    if tag_id:
        messages = [item for item in messages if any(tag["id"] == tag_id for tag in item.get("tags") or [])]
    payload = tag_page(session)
    payload["accounts"] = [_account_out(row) for row in _all_accounts(session)]
    payload["messages"] = messages
    payload["sync"] = _sync_info()
    payload["notify"] = notify_state(session)
    return payload


def project_mail(session: Session, project_id: int, unread_only: bool, include_archived: bool, query: str) -> dict:
    return {
        "accounts": [_account_out(row) for row in _accounts(session, project_id)],
        "rules": [_rule_out(row, project_id) for row in _rules(session, project_id)],
        "messages": _message_list(session, project_id, unread_only, include_archived, query),
        "fields": _choices(project_id, "rules.fields"),
        "ops": _choices(project_id, "rules.ops"),
        "actions": _choices(project_id, "rules.actions"),
        "sync": _sync_info(),
    }


def import_raw(session: Session, project_id: int, user_id: int, raw: bytes) -> dict:
    moves: list[tuple[int, str, int | None]] = []
    outcome, row = _ingest(session, project_id, user_id, raw, None, None, "", notify=True, moves=moves)
    session.commit()
    _run_moves(moves)
    return {"status": outcome, "id": row.id if row is not None else None}


def get_message(session: Session, project_id: int, user_id: int, message_id: int) -> dict:
    row = _message(session, project_id, message_id)
    if not row.read and get_bool("mail", "message.mark_read_on_open", project_id=project_id or None):
        row.read = True
        session.flush()
        with log_scope("mail", "read", user_id=user_id):
            logger.info("mail read id={}", row.id)
    payload = _message_out(session, row, full=True)
    payload["thread"], payload["thread_total"] = _thread_out(session, row, project_id)
    _attach_tags(session, [payload])
    return payload


def update_message(session: Session, project_id: int, user_id: int, message_id: int, fields: dict) -> dict:
    row = _message(session, project_id, message_id)
    if "read" in fields and fields["read"] is not None:
        row.read = bool(fields["read"])
    if "archived" in fields and fields["archived"] is not None:
        row.archived = bool(fields["archived"])
        if row.archived:
            enqueue(
                session,
                MAIL_ARCHIVED,
                {"title": "Письмо в архиве", "subject": _title(row, project_id), "link": "/mail/" + str(row.id)},
                user_id=user_id,
            )
    session.flush()
    payload = _message_out(session, row, full=True)
    payload["thread"], payload["thread_total"] = _thread_out(session, row, project_id)
    _attach_tags(session, [payload])
    return payload


def delete_message(session: Session, project_id: int, user_id: int, message_id: int) -> None:
    row = _message(session, project_id, message_id)
    title = _title(row, project_id)
    session.delete(row)
    session.flush()
    enqueue(session, MAIL_DELETED, {"title": "Письмо удалено", "subject": title, "link": "/mail"}, user_id=user_id)
    with log_scope("mail", "message.delete", user_id=user_id):
        logger.info("mail message deleted id={}", message_id)


def set_message_tag(session: Session, user_id: int, message_id: int, tag_id: int, on: bool) -> dict:
    row = session.get(MailMessage, message_id)
    tag = session.get(MailTag, tag_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    if tag is None:
        raise HTTPException(status_code=404, detail="Хештег не найден")
    pin = session.scalars(select(MailTagPin).where(MailTagPin.message_id == message_id, MailTagPin.tag_id == tag_id)).first()
    hide = session.scalars(select(MailTagHide).where(MailTagHide.message_id == message_id, MailTagHide.tag_id == tag_id)).first()
    if on:
        if hide is not None:
            session.delete(hide)
        if pin is None:
            session.add(MailTagPin(message_id=message_id, tag_id=tag_id))
    else:
        if pin is not None:
            session.delete(pin)
        if hide is None:
            session.add(MailTagHide(message_id=message_id, tag_id=tag_id))
    session.flush()
    payload = _message_out(session, row, full=False)
    _attach_tags(session, [payload])
    return payload


def download_attachment(session: Session, project_id: int, user_id: int, message_id: int, section: str) -> dict:
    row = _message(session, project_id, message_id)
    if row.account_id is None or not row.uid:
        raise HTTPException(status_code=400, detail="Сырое письмо уже недоступно")
    account = session.get(MailAccount, row.account_id)
    if account is None or account.auth_blocked:
        raise HTTPException(status_code=400, detail="Ящик недоступен")
    password = _unpack(account)
    if not password:
        raise HTTPException(status_code=400, detail="У ящика нет пароля")
    creds = (account.host, account.port, account.use_ssl, account.username, password, row.folder or account.folder, row.uid, _timeout(account.project_id))
    session.commit()
    raw, error = imap_client.pull_uid(*creds)
    if error or not raw:
        raise HTTPException(status_code=400, detail=_error_text(error or "Вложение не забрали", password))
    filename, mime, data = parse.part_bytes(raw, section, _limits())
    stored = save_bytes(session, data, filename, mime, user_id)
    session.add(MailAttachment(message_id=row.id, file_id=stored.id, filename=stored.original_name))
    session.flush()
    add_link(session, stored.id, project_id=project_id or None, module="mail", entity_type="mail_message", entity_id=row.id)
    return {"file_id": stored.id, "filename": stored.original_name}


def _message_list(session, project_id, unread_only, include_archived, query) -> list[dict]:
    statement = select(MailMessage).options(defer(MailMessage.html_body))
    if not include_archived:
        statement = statement.where(MailMessage.archived.is_(False))
    if unread_only:
        statement = statement.where(MailMessage.read.is_(False))
    scope = project_id or None
    scan = get_int("mail", "threads.scan_limit", project_id=scope) if get_bool("mail", "threads.enabled", project_id=scope) else (
        get_int("mail", "list.scan_limit", project_id=scope) if project_id else get_int("mail", "list.limit", project_id=scope)
    )
    rows = list(session.scalars(statement.order_by(MailMessage.received_at.desc(), MailMessage.id.desc()).limit(scan)).all())
    if project_id:
        rules = [rule for rule in _rules(session, project_id) if rule.enabled]
        rows = [row for row in rows if _row_matches(rules, row, project_id)]
    needle = (query or "").strip().casefold()
    if needle:
        rows = [row for row in rows if needle in _search_blob(row).casefold()]
    limit = get_int("mail", "list.limit", project_id=scope)
    if get_bool("mail", "threads.enabled", project_id=scope):
        messages = _grouped_messages(session, rows, project_id)[:limit]
    else:
        messages = [_message_out(session, row, full=False) for row in rows[:limit]]
    _attach_tags(session, messages)
    return messages
