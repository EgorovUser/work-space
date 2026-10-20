"""Письма: общий ящик, ящик проекта, карточка письма, CRUD, импорт файла."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from app.core.events_bus import publish as publish_event
from app.core.events_catalog import MAIL_ARCHIVED, MAIL_DELETED
from app.core.files import add_link, save_bytes
from app.core.models import StoredFile
from app.modules.projects.models import Project
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
    _meta,
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


def mailbox(session: Session, unread_only: bool, include_archived: bool, query: str, tag_id: int = 0, offset: int = 0) -> dict:
    unread_total = session.scalar(
        select(func.count()).select_from(MailMessage).where(MailMessage.read.is_(False), MailMessage.archived.is_(False))
    )
    messages = _message_list(session, None, unread_only, include_archived, query, tag_id=tag_id, offset=offset)
    payload = tag_page(session)
    payload["accounts"] = [_account_out(row) for row in _all_accounts(session)]
    payload["messages"] = messages
    payload["sync"] = _sync_info()
    payload["notify"] = notify_state(session)
    payload["page"] = {"offset": offset, "limit": _page_limit(None)}
    payload["unread"] = int(unread_total or 0)
    return payload


def project_mail(session: Session, project_id: int, unread_only: bool, include_archived: bool, query: str, offset: int = 0) -> dict:
    return {
        "accounts": [_account_out(row) for row in _accounts(session, project_id)],
        "rules": [_rule_out(row, project_id) for row in _rules(session, project_id)],
        "messages": _message_list(session, project_id, unread_only, include_archived, query, offset=offset),
        "fields": _choices(project_id, "rules.fields"),
        "ops": _choices(project_id, "rules.ops"),
        "actions": _choices(project_id, "rules.actions"),
        "sync": _sync_info(),
    }


def import_raw(session: Session, project_id: int, user_id: int, raw: bytes) -> dict:
    moves: list[tuple[int, str, int | None]] = []
    outcome, row = _ingest(session, project_id, user_id, raw, None, None, "", notify=True, moves=moves)
    if outcome == "stored" and row is not None:
        # Ручной импорт: сервера-источника у письма нет, вложения
        # сохраняем сразу — позже взять их неоткуда (патч N: кнопка
        # «В документы» и «Скачать» должны работать и для импорта).
        _store_raw_attachments(session, project_id, user_id, row, raw)
    session.commit()
    _run_moves(moves)
    if outcome == "stored":
        publish_event("mail.changed")
    return {"status": outcome, "id": row.id if row is not None else None}


def _store_raw_attachments(session: Session, project_id: int, user_id: int, row: MailMessage, raw: bytes) -> None:
    for item in _meta(row):
        section = str(item.get("section") or "")
        if not section:
            continue
        try:
            filename, mime, data = parse.part_bytes(raw, section, _limits())
        except ValueError:
            # Слишком большое вложение или битая секция: останется
            # метаданные, как раньше.
            continue
        stored = save_bytes(session, data, filename, mime, user_id)
        session.add(MailAttachment(message_id=row.id, file_id=stored.id, filename=stored.original_name))
        add_link(session, stored.id, project_id=project_id or None, module="mail", entity_type="mail_message", entity_id=row.id)
    with log_scope("mail", "import.attachments", user_id=user_id):
        logger.info("imported attachments stored message={}", row.id)


def get_message(session: Session, project_id: int, user_id: int, message_id: int) -> dict:
    row = _message(session, project_id, message_id)
    if not row.read and get_bool("mail", "message.mark_read_on_open", project_id=project_id or None):
        row.read = True
        session.flush()
        publish_event("mail.changed")
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
    publish_event("mail.changed")
    payload = _message_out(session, row, full=True)
    payload["thread"], payload["thread_total"] = _thread_out(session, row, project_id)
    _attach_tags(session, [payload])
    return payload


def delete_message(session: Session, project_id: int, user_id: int, message_id: int) -> None:
    row = _message(session, project_id, message_id)
    title = _title(row, project_id)
    session.delete(row)
    session.flush()
    publish_event("mail.changed")
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


def attachment_to_document(
    session: Session,
    project_id: int | None,
    user_id: int,
    message_id: int,
    section: str,
    target_project_id: int | None = None,
) -> dict:
    """Вложение письма — в «Документы» одним действием (патч N).

    Если вложение ещё не выгружено с сервера (в письме только метаданные),
    сначала забираем его как «Скачать вложение», затем создаём документ
    из уже сохранённого файла — повторной загрузки не происходит.
    project_id — ящик, из которого читаем (0 для общего); target_project_id
    — куда положить документ (по умолчанию проект письма или общий ящик).
    """
    from app.modules.documents import service as documents_service

    row = _message(session, project_id or 0, message_id)
    meta = _meta(row)
    entry = next((item for item in meta if str(item.get("section") or "") == section), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Вложение не найдено")
    filename = entry.get("filename") or "файл"

    stored_row = session.scalars(
        select(MailAttachment).where(MailAttachment.message_id == row.id, MailAttachment.filename == filename)
    ).first()
    if stored_row is None:
        # Ещё не выгружено: забираем с IMAP-сервера тем же путём, что и
        # кнопка «Скачать вложение» (метод сам сохранит файл и связь).
        pulled = download_attachment(session, project_id or 0, user_id, message_id, section)
        file_id = pulled["file_id"]
    else:
        file_id = stored_row.file_id

    stored = session.get(StoredFile, file_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Файл вложения не найден")

    destination = target_project_id or row.project_id
    if not destination:
        raise HTTPException(status_code=400, detail="Укажите проект для документа")
    if session.get(Project, destination) is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    subject = (row.subject or "").strip()
    note = "Из письма" + (": " + subject if subject else "")
    document = documents_service.create_from_stored(
        session,
        destination,
        user_id,
        stored,
        title="",
        note=note,
    )
    with log_scope("mail", "attachment.document", user_id=user_id):
        logger.info("mail attachment to document message={} section={} document={}", message_id, section, document["id"])
    return {"document_id": document["id"], "title": document["title"], "project_id": destination}


def _page_limit(project_id: int | None) -> int:
    return get_int("mail", "list.limit", project_id=project_id or None)


def _message_list(session, project_id, unread_only, include_archived, query, tag_id: int = 0, offset: int = 0) -> list[dict]:
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
    if get_bool("mail", "threads.enabled", project_id=scope):
        messages = _grouped_messages(session, rows, project_id)
    else:
        messages = [_message_out(session, row, full=False) for row in rows]
    _attach_tags(session, messages)
    if tag_id:
        messages = [item for item in messages if any(tag["id"] == tag_id for tag in item.get("tags") or [])]
    # Постраничная выдача: старые письма доступны по кнопке «Показать ещё»,
    # а не только правкой глобальной настройки list.limit.
    offset = max(0, int(offset or 0))
    limit = _page_limit(scope)
    return messages[offset : offset + limit]
