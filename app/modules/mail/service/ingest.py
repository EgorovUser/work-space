"""Загрузка писем: парсинг, безопасная вставка, события, раскладка по проектам.

Именно здесь применена точечная правка: вставка письма идёт через
``add_message_safe``, чтобы гонка джобы и ручного fetch не роняла
транзакцию из-за уникального индекса (account_id, folder, uid).
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_catalog import MAIL_EVENT, MAIL_FILED, MAIL_RECEIVED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int
from app.modules.mail import parse
from app.modules.mail.ingest_safe import add_message_safe
from app.modules.mail.models import MailAccount, MailEvent, MailFiling, MailMessage
from app.modules.mail.service._matching import _row_matches
from app.modules.mail.service._queries import _rules
from app.modules.mail.service._serialize import _title
from app.modules.mail.service._settings import _format_when, _limits
from app.modules.mail.service.notify import _filed_matches_notify, _letter_matches_notify
from app.modules.projects.models import Project
from app.modules.projects.service import touch_project


def _ingest(session, project_id, user_id, raw: bytes, account: MailAccount | None, uid: int | None, folder: str, notify: bool = True, moves: list | None = None):
    try:
        parsed = parse.parse_message(raw, _limits())
    except ValueError:
        logger.warning("mail parse failed project={}", project_id)
        return "skipped", None
    if account is not None and uid:
        duplicate = session.scalars(
            select(MailMessage).where(MailMessage.account_id == account.id, MailMessage.folder == folder, MailMessage.uid == uid)
        ).first()
        if duplicate is not None:
            _file_message(session, user_id, duplicate, moves)
            return "duplicate", duplicate
    if parsed["rfc_message_id"]:
        duplicate = session.scalars(
            select(MailMessage).where(MailMessage.project_id == project_id, MailMessage.rfc_message_id == parsed["rfc_message_id"])
        ).first()
        if duplicate is not None:
            _file_message(session, user_id, duplicate, moves)
            return "duplicate", duplicate
    now = utcnow()
    row = MailMessage(
        project_id=project_id,
        account_id=account.id if account is not None else None,
        uid=uid,
        folder=folder or "",
        rfc_message_id=parsed["rfc_message_id"],
        from_name=parsed["from_name"],
        from_addr=parsed["from_addr"],
        to_addr=parsed["to_addr"],
        subject=parsed["subject"],
        body=parsed["body"],
        html_body=parsed.get("html") or "",
        received_at=parsed["received_at"],
        read=False,
        archived=False,
        rule_id=None,
        created_at=now,
    )
    if add_message_safe(session, row) is None:
        return "duplicate", None
    _remember_attachments(row, parsed["attachments"])
    _remember_events(session, row, parsed.get("events") or [], notify=notify)
    if project_id:
        touch_project(session, project_id)
    if notify and get_bool("mail", "fetch.notify_new") and _letter_matches_notify(session, row):
        enqueue(
            session,
            MAIL_RECEIVED,
            {"message_id": row.id, "subject": _title(row, project_id), "link": "/mail/" + str(row.id), "title": "Новое письмо"},
            user_id=user_id,
        )
    _file_message(session, user_id, row, moves)
    with log_scope("mail", "store", user_id=user_id):
        logger.info("mail stored id={}", row.id)
    return "stored", row


def _remember_attachments(row: MailMessage, files: list[dict]) -> None:
    meta = [
        {
            "filename": item.get("filename") or "файл",
            "mime": item.get("mime") or "",
            "size": int(item.get("size") or 0),
            "section": str(item.get("section") or ""),
        }
        for item in files
    ]
    row.attachments_json = json.dumps(meta, ensure_ascii=False)


def _remember_events(session: Session, row: MailMessage, events: list[dict], notify: bool = True) -> None:
    for item in events:
        start = item.get("starts_at")
        if start is None:
            continue
        session.add(
            MailEvent(
                message_id=row.id,
                ical_uid=item.get("uid") or "",
                summary=item.get("summary") or "Событие",
                starts_at=start,
                ends_at=item.get("ends_at"),
                location=item.get("location") or "",
                created_at=utcnow(),
            )
        )
    if events and notify:
        first = next((item for item in events if item.get("starts_at") is not None), events[0])
        enqueue(
            session,
            MAIL_EVENT,
            {
                "title": "События из почты",
                "subject": first.get("summary") or _title(row, row.project_id),
                "when": _format_when(first["starts_at"]) if first.get("starts_at") is not None else "",
                "location": first.get("location") or "",
                "message_id": row.id,
                "link": "/mail/" + str(row.id),
            },
            user_id=None,
        )


def _notify_event(session: Session, row: MailEvent, event_type: str, title: str) -> None:
    message = session.get(MailMessage, row.message_id)
    enqueue(
        session,
        event_type,
        {
            "title": title,
            "subject": row.summary or "",
            "when": _format_when(row.starts_at),
            "location": row.location or "",
            "message_id": row.message_id,
            "link": "/mail/" + str(row.message_id),
            "dedup_key": event_type + ":" + str(row.id),
        },
        user_id=None,
    )
    if message is not None:
        logger.info("mail event reminder type={} message={}", event_type, message.id)


def _file_project(session: Session, project_id: int, user_id: int, moves: list | None = None) -> None:
    project = session.get(Project, project_id)
    if project is None or project.archived:
        return
    rules = [rule for rule in _rules(session, project_id) if rule.enabled]
    if not rules:
        return
    scan = get_int("mail", "list.scan_limit", project_id=project_id)
    rows = session.scalars(select(MailMessage).order_by(MailMessage.id.desc()).limit(scan)).all()
    for row in rows:
        if _row_matches(rules, row, project_id):
            _file_one(session, user_id, row, project, moves)


def _file_message(session: Session, user_id: int | None, row: MailMessage, moves: list | None = None) -> None:
    projects = session.scalars(select(Project).where(Project.archived.is_(False))).all()
    for project in projects:
        rules = [rule for rule in _rules(session, project.id) if rule.enabled]
        if rules and _row_matches(rules, row, project.id):
            _file_one(session, user_id, row, project, moves)


def _file_one(session: Session, user_id: int | None, row: MailMessage, project: Project, moves: list | None) -> None:
    exists = session.scalars(select(MailFiling).where(MailFiling.message_id == row.id, MailFiling.project_id == project.id)).first()
    if exists is not None:
        return
    session.add(MailFiling(message_id=row.id, project_id=project.id, created_at=utcnow()))
    session.flush()
    if get_bool("mail", "filters.move") and row.uid and row.account_id:
        account = session.get(MailAccount, row.account_id)
        if account is not None and not account.auth_blocked:
            if moves is not None:
                moves.append((row.id, project.name, user_id))
    if get_bool("mail", "filters.notify") and _filed_matches_notify(session, row):
        enqueue(
            session,
            MAIL_FILED,
            {
                "title": "Письмо в проекте " + project.name,
                "subject": _title(row, project.id),
                "project_id": project.id,
                "message_id": row.id,
                "link": "/projects/" + str(project.id) + "/mail/" + str(row.id),
            },
            user_id=user_id,
        )
