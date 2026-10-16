"""Почта: общий ящик, фильтры проектов, хештеги, события."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, defer

from app.core.db import session_scope, utcnow
from app.core.events_catalog import (
    MAIL_ARCHIVED,
    MAIL_AUTH_FAILED,
    MAIL_DELETED,
    MAIL_EVENT,
    MAIL_EVENT_SOON,
    MAIL_EVENT_TODAY,
    MAIL_FILED,
    MAIL_RECEIVED,
)
from app.core.files import add_link, save_bytes
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get, get_bool, get_int, get_str, set_value
from app.modules.mail import crypto, imap_client, parse
from app.modules.mail.models import (
    MailAccount,
    MailAttachment,
    MailEvent,
    MailFiling,
    MailMessage,
    MailNotifyRule,
    MailRule,
    MailTag,
    MailTagHide,
    MailTagPin,
    MailTagRule,
)
from app.modules.projects.models import Project
from app.modules.projects.service import touch_project


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


def tag_page(session: Session) -> dict:
    return {
        "tags": _tag_catalog(session),
        "tag_fields": _choices(0, "tags.fields"),
        "tag_ops": _choices(0, "tags.ops"),
        "tag_default_color": get_str("mail", "tags.default_color"),
    }


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


def create_account(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    now = utcnow()
    row = MailAccount(
        project_id=0,
        name=_clean(fields.get("name") or "", "account.name.max_length", "Укажите название"),
        host=_clean(fields.get("host") or "", "account.host.max_length", "Укажите сервер"),
        port=_port(fields.get("port"), project_id),
        use_ssl=_ssl(fields.get("use_ssl"), project_id),
        username=_clip(fields.get("username") or "", "account.username.max_length"),
        password_enc=_pack(_password(fields.get("password") or "", required=True)),
        folder=_folder(fields.get("folder"), project_id),
        enabled=True if fields.get("enabled") is None else bool(fields.get("enabled")),
        last_uid=0,
        last_error="",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    session.commit()
    with log_scope("mail", "account.create", user_id=user_id):
        logger.info("mail account id={} host={}", row.id, row.host)
    _fetch_row(session, row, user_id)
    return _account_out(row)


def update_account(session: Session, project_id: int, user_id: int, account_id: int, fields: dict) -> dict:
    row = _account(session, project_id, account_id)
    if "name" in fields and fields["name"] is not None:
        row.name = _clean(fields["name"], "account.name.max_length", "Укажите название")
    if "host" in fields and fields["host"] is not None:
        row.host = _clean(fields["host"], "account.host.max_length", "Укажите сервер")
    if "port" in fields and fields["port"] is not None:
        row.port = _port(fields["port"], project_id)
    if "use_ssl" in fields and fields["use_ssl"] is not None:
        row.use_ssl = bool(fields["use_ssl"])
    if "username" in fields and fields["username"] is not None:
        row.username = _clip(fields["username"], "account.username.max_length")
    if "folder" in fields and fields["folder"] is not None:
        row.folder = _folder(fields["folder"], project_id)
    if "enabled" in fields and fields["enabled"] is not None:
        row.enabled = bool(fields["enabled"])
    if "password" in fields and fields["password"]:
        row.password_enc = _pack(_password(fields["password"], required=True))
        row.auth_blocked = False
        row.auth_notified = False
        row.last_error = ""
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    if "password" in fields and fields["password"]:
        session.commit()
        _fetch_row(session, row, user_id)
    with log_scope("mail", "account.update", user_id=user_id):
        logger.info("mail account updated id={}", row.id)
    return _account_out(row)


def delete_account(session: Session, project_id: int, user_id: int, account_id: int) -> None:
    row = _account(session, project_id, account_id)
    session.delete(row)
    touch_project(session, project_id)
    session.flush()
    with log_scope("mail", "account.delete", user_id=user_id):
        logger.info("mail account deleted id={}", account_id)


def check_account(session: Session, project_id: int, user_id: int, account_id: int) -> dict:
    row = _account(session, project_id, account_id)
    password = _unpack(row)
    error = None if password else "Укажите пароль"
    if password:
        host, port, use_ssl, username, folder = row.host, row.port, row.use_ssl, row.username, row.folder
        session.commit()
        error = imap_client.check_login(host, port, use_ssl, username, password, folder, _timeout(project_id))
        row = session.get(MailAccount, account_id)
    row.last_error = _error_text(error or "", password or "")
    row.last_checked_at = utcnow()
    row.updated_at = row.last_checked_at
    session.flush()
    with log_scope("mail", "account.check", user_id=user_id):
        logger.info("mail check id={} ok={}", row.id, not row.last_error)
    return {"ok": not row.last_error, "error": row.last_error}


def fetch_account(session: Session, project_id: int, user_id: int | None, account_id: int) -> dict:
    row = _account(session, project_id, account_id)
    return _fetch_row(session, row, user_id)


def create_rule(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    position = session.scalar(select(func.max(MailRule.position)).where(MailRule.project_id == project_id)) or 0
    row = MailRule(
        project_id=project_id,
        name=_clean(fields.get("name") or "", "rule.name.max_length", "Укажите название"),
        enabled=True if fields.get("enabled") is None else bool(fields.get("enabled")),
        position=int(position) + 1,
        field=_choice(fields.get("field") or "", project_id, "rules.fields", "Поле не из списка"),
        op=_choice(fields.get("op") or "", project_id, "rules.ops", "Операция не из списка"),
        value=_clean(fields.get("value") or "", "rule.value.max_length", "Укажите значение"),
        action="keep",
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    moves: list[tuple[int, str, int | None]] = []
    _file_project(session, project_id, user_id, moves)
    session.commit()
    _run_moves(moves)
    with log_scope("mail", "rule.create", user_id=user_id):
        logger.info("mail rule id={}", row.id)
    return _rule_out(row, project_id)


def update_rule(session: Session, project_id: int, user_id: int, rule_id: int, fields: dict) -> dict:
    row = _rule(session, project_id, rule_id)
    if "name" in fields and fields["name"] is not None:
        row.name = _clean(fields["name"], "rule.name.max_length", "Укажите название")
    if "enabled" in fields and fields["enabled"] is not None:
        row.enabled = bool(fields["enabled"])
    if "field" in fields and fields["field"] is not None:
        row.field = _choice(fields["field"], project_id, "rules.fields", "Поле не из списка")
    if "op" in fields and fields["op"] is not None:
        row.op = _choice(fields["op"], project_id, "rules.ops", "Операция не из списка")
    if "value" in fields and fields["value"] is not None:
        row.value = _clean(fields["value"], "rule.value.max_length", "Укажите значение")
    touch_project(session, project_id)
    session.flush()
    with log_scope("mail", "rule.update", user_id=user_id):
        logger.info("mail rule updated id={}", row.id)
    return _rule_out(row, project_id)


def delete_rule(session: Session, project_id: int, user_id: int, rule_id: int) -> None:
    row = _rule(session, project_id, rule_id)
    session.delete(row)
    touch_project(session, project_id)
    session.flush()
    with log_scope("mail", "rule.delete", user_id=user_id):
        logger.info("mail rule deleted id={}", rule_id)


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


def test_account(session: Session, user_id: int, account_id: int) -> dict:
    row = _account_any(session, account_id)
    row.auth_blocked = False
    password = _unpack(row)
    if not password:
        _block(session, row, "Укажите пароль", "", user_id)
        return {"ok": False, "error": row.last_error, "subject": ""}
    host, port, use_ssl, username, folder = row.host, row.port, row.use_ssl, row.username, row.folder
    timeout = _timeout(row.project_id)
    session.commit()
    error = imap_client.check_login(host, port, use_ssl, username, password, folder, timeout)
    row = session.get(MailAccount, account_id)
    if row is None:
        return {"ok": False, "error": "Ящик удалён", "subject": ""}
    if _is_auth(error):
        _block(session, row, error or "", password, user_id)
        return {"ok": False, "error": row.last_error, "subject": ""}
    if error:
        row.last_error = _error_text(error, password)
        row.last_checked_at = utcnow()
        session.flush()
        return {"ok": False, "error": row.last_error, "subject": ""}
    session.commit()
    messages, pull_error = imap_client.pull(host, port, use_ssl, username, password, folder, 0, 1, timeout)
    row = session.get(MailAccount, account_id)
    if row is None:
        return {"ok": False, "error": "Ящик удалён", "subject": ""}
    if _is_auth(pull_error):
        _block(session, row, pull_error or "", password, user_id)
        return {"ok": False, "error": row.last_error, "subject": ""}
    subject = ""
    if messages:
        try:
            parsed = parse.parse_message(messages[0][1], _limits())
            subject = parsed.get("subject") or ""
            moves: list[tuple[int, str, int | None]] = []
            _ingest(session, 0, user_id, messages[0][1], row, messages[0][0], folder, notify=False, moves=moves)
            session.commit()
            _run_moves(moves)
            row = session.get(MailAccount, account_id)
        except ValueError:
            subject = ""
    if row is not None:
        row.auth_blocked = False
        row.auth_notified = False
        row.last_error = ""
        row.last_checked_at = utcnow()
        session.flush()
    return {"ok": True, "error": "", "subject": subject or "Вход прошёл, в папке нет писем"}


def place_message(session: Session, user_id: int | None, message_id: int, folder_name: str, move: bool) -> dict:
    row = session.get(MailMessage, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    if row.account_id is None or not row.uid:
        raise HTTPException(status_code=400, detail="Это письмо загружено файлом, на сервере его нет")
    account = session.get(MailAccount, row.account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="Ящик уже удалён")
    if account.auth_blocked:
        raise HTTPException(status_code=400, detail="Пароль ящика не подошёл. Сначала смените его")
    password = _unpack(account)
    if not password:
        raise HTTPException(status_code=400, detail="У ящика нет пароля")
    name = (folder_name or "").strip() or "Проект"
    creds = (
        account.host,
        account.port,
        account.use_ssl,
        account.username,
        password,
        row.folder or account.folder,
        row.uid,
        name,
        move,
        _timeout(account.project_id),
        row.rfc_message_id or "",
    )
    account_id = account.id
    session.commit()
    error, new_uid = imap_client.copy_message(*creds)
    account = session.get(MailAccount, account_id)
    row = session.get(MailMessage, message_id)
    if account is not None and _is_auth(error):
        _block(session, account, error or "", password, user_id)
    if error:
        raise HTTPException(status_code=400, detail=_error_text(error, password))
    if row is not None and move and new_uid is not None:
        row.folder = name
        row.uid = new_uid or None
        session.flush()
    with log_scope("mail", "folder", user_id=user_id):
        logger.info("mail folder message={} move={} folder={}", message_id, move, name)
    return {"ok": True, "folder": name}


def poll_accounts() -> None:
    if not get_bool("mail", "job.enabled"):
        return
    with session_scope() as session:
        ids = list(session.scalars(select(MailAccount.id).where(MailAccount.enabled.is_(True))).all())
    for account_id in ids:
        try:
            with session_scope() as session:
                row = session.get(MailAccount, account_id)
                if row is not None and row.enabled and not row.auth_blocked:
                    _fetch_row(session, row, None)
        except Exception:
            logger.exception("mail poll failed account={}", account_id)


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


def create_tag(session: Session, user_id: int, fields: dict) -> dict:
    name = _clean(fields.get("name") or "", "tags.name.max_length", "Укажите название хештега")
    color = _tag_color(fields.get("color") or "")
    raw_rules = fields.get("rules") or []
    if not isinstance(raw_rules, list) or not any(isinstance(item, dict) and str(item.get("value") or "").strip() for item in raw_rules):
        raise HTTPException(status_code=400, detail="Нужно хотя бы одно условие: вручную хештег на письмо больше не ставится")
    position = session.scalar(select(func.max(MailTag.position))) or 0
    tag = MailTag(name=name, color=color, enabled=True, position=int(position) + 1, created_at=utcnow())
    session.add(tag)
    session.flush()
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        field, op = _tag_pair(item.get("field") or "", item.get("op") or "")
        value = _clean(item.get("value") or "", "rule.value.max_length", "Укажите значение условия")
        if field == "received":
            try:
                value = datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Дата в виде ГГГГ-ММ-ДД") from exc
        session.add(MailTagRule(tag_id=tag.id, field=field, op=op, value=value))
    session.flush()
    with log_scope("mail", "tag.create", user_id=user_id):
        logger.info("mail tag id={}", tag.id)
    return _tag_out(session, tag)


def delete_tag(session: Session, user_id: int, tag_id: int) -> None:
    tag = session.get(MailTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Хештег не найден")
    session.delete(tag)
    session.flush()
    with log_scope("mail", "tag.delete", user_id=user_id):
        logger.info("mail tag deleted id={}", tag_id)


def notify_state(session: Session) -> dict:
    rules = session.scalars(select(MailNotifyRule).order_by(MailNotifyRule.position, MailNotifyRule.id)).all()
    return {
        "mode": get_str("mail", "notify.mode"),
        "match": get_str("mail", "notify.match"),
        "gate_filed": get_bool("mail", "notify.gate_filed"),
        "modes": _choices(0, "notify.modes"),
        "matches": _choices(0, "notify.matches"),
        "fields": _choices(0, "notify.fields"),
        "ops": _choices(0, "notify.ops"),
        "rules": [_notify_rule_out(session, rule) for rule in rules],
    }


def save_notify(session: Session, user_id: int, fields: dict) -> dict:
    mode = _choice(str(fields.get("mode") or ""), 0, "notify.modes", "Неизвестный режим")
    match = _choice(str(fields.get("match") or ""), 0, "notify.matches", "Неизвестное сочетание условий")
    gate = fields.get("gate_filed")
    if not isinstance(gate, bool):
        raise HTTPException(status_code=400, detail="Укажите, фильтровать ли письма проекта")
    set_value("mail", "notify.mode", "global", mode, actor_id=user_id)
    set_value("mail", "notify.match", "global", match, actor_id=user_id)
    set_value("mail", "notify.gate_filed", "global", gate, actor_id=user_id)
    with log_scope("mail", "notify", user_id=user_id):
        logger.info("mail notify mode={} match={}", mode, match)
    return notify_state(session)


def create_notify_rule(session: Session, user_id: int, fields: dict) -> dict:
    field, op = _notify_pair(fields.get("field") or "", fields.get("op") or "")
    raw = str(fields.get("value") or "").strip()
    if field == "tag":
        value = _notify_tag_value(session, raw)
    else:
        value = _clean(raw, "rule.value.max_length", "Укажите значение условия")
    position = session.scalar(select(func.max(MailNotifyRule.position))) or 0
    session.add(MailNotifyRule(field=field, op=op, value=value, position=int(position) + 1))
    session.flush()
    with log_scope("mail", "notify.rule", user_id=user_id):
        logger.info("mail notify rule field={} op={}", field, op)
    return notify_state(session)


def delete_notify_rule(session: Session, user_id: int, rule_id: int) -> dict:
    row = session.get(MailNotifyRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Условие не найдено")
    session.delete(row)
    session.flush()
    with log_scope("mail", "notify.rule", user_id=user_id):
        logger.info("mail notify rule deleted id={}", rule_id)
    return notify_state(session)


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


def ensure_schema() -> None:
    with session_scope() as session:
        rows = session.execute(text("PRAGMA table_info(mail_messages)")).all()
        names = {row[1] for row in rows}
        if "attachments_json" not in names:
            session.execute(text("ALTER TABLE mail_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''"))
        if "html_body" not in names:
            session.execute(text("ALTER TABLE mail_messages ADD COLUMN html_body TEXT NOT NULL DEFAULT ''"))
        accounts = session.execute(text("PRAGMA table_info(mail_accounts)")).all()
        account_names = {row[1] for row in accounts}
        if "backfill_uid" not in account_names:
            session.execute(text("ALTER TABLE mail_accounts ADD COLUMN backfill_uid INTEGER NOT NULL DEFAULT 0"))
        if "auth_blocked" not in account_names:
            session.execute(text("ALTER TABLE mail_accounts ADD COLUMN auth_blocked INTEGER NOT NULL DEFAULT 0"))
        if "auth_notified" not in account_names:
            session.execute(text("ALTER TABLE mail_accounts ADD COLUMN auth_notified INTEGER NOT NULL DEFAULT 0"))
        event_rows = session.execute(text("PRAGMA table_info(mail_events)")).all()
        event_names = {row[1] for row in event_rows}
        if event_rows and "reminded_soon" not in event_names:
            session.execute(text("ALTER TABLE mail_events ADD COLUMN reminded_soon INTEGER NOT NULL DEFAULT 0"))
        if event_rows and "reminded_day" not in event_names:
            session.execute(text("ALTER TABLE mail_events ADD COLUMN reminded_day TEXT NOT NULL DEFAULT ''"))


def _fetch_row(session: Session, row: MailAccount, user_id: int | None) -> dict:
    if row.auth_blocked:
        return {"fetched": 0, "error": row.last_error or "Пароль не подошёл", "blocked": True, "backfill": _backfill_state(row)}
    password = _unpack(row)
    if not password:
        _block(session, row, "Укажите пароль", "", user_id)
        return {"fetched": 0, "error": row.last_error, "blocked": True, "backfill": _backfill_state(row)}
    limit = get_int("mail", "fetch.batch_size", project_id=row.project_id)
    timeout = _timeout(row.project_id)
    account_id = row.id
    host, port, use_ssl, username, folder, last_uid = row.host, row.port, row.use_ssl, row.username, row.folder, row.last_uid
    session.commit()
    messages, error = imap_client.pull(host, port, use_ssl, username, password, folder, last_uid, limit, timeout)
    row = session.get(MailAccount, account_id)
    if row is None:
        return {"fetched": 0, "error": "Ящик удалён", "blocked": False, "backfill": "done"}
    if _is_auth(error):
        _block(session, row, error or "", password, user_id)
        return {"fetched": 0, "error": row.last_error, "blocked": True, "backfill": _backfill_state(row)}
    moves: list[tuple[int, str, int | None]] = []
    stored = _store_batch(session, row, user_id, messages, notify=True, moves=moves)
    if messages:
        row.last_uid = max(row.last_uid, max(uid for uid, _raw in messages))
    known = set(
        session.scalars(select(MailMessage.uid).where(MailMessage.account_id == account_id, MailMessage.uid.is_not(None))).all()
    )
    known.update(uid for uid, _raw in messages)
    since = _lookback_token(row.project_id)
    session.commit()
    recent, recent_error = imap_client.pull_recent(
        host, port, use_ssl, username, password, folder, since, known, limit, timeout
    )
    row = session.get(MailAccount, account_id)
    if row is None:
        return {"fetched": stored, "error": "Ящик удалён", "blocked": False, "backfill": "done"}
    if _is_auth(recent_error):
        _block(session, row, recent_error or "", password, user_id)
        return {"fetched": stored, "error": row.last_error, "blocked": True, "backfill": _backfill_state(row)}
    if recent:
        stored += _store_batch(session, row, user_id, recent, notify=False, moves=moves)
        row.last_uid = max(row.last_uid, max(uid for uid, _raw in recent))
    if recent_error and not error:
        error = recent_error
    session.commit()
    _run_moves(moves)
    if get_bool("mail", "fetch.backfill") and not error:
        times = get_int("mail", "fetch.batches_per_run")
        for _ in range(max(1, times)):
            row = session.get(MailAccount, account_id)
            if row is None or row.auth_blocked or row.backfill_uid < 0:
                break
            got = _backfill(session, row, user_id, password, limit, timeout)
            stored += got
            if got == 0:
                break
    row = session.get(MailAccount, account_id)
    if row is None:
        return {"fetched": stored, "error": "", "blocked": False, "backfill": "done"}
    row.last_error = _error_text(error or "", password)
    row.last_checked_at = utcnow()
    row.updated_at = row.last_checked_at
    session.flush()
    with log_scope("mail", "fetch", user_id=user_id):
        logger.info("mail fetch account={} stored={} blocked={}", row.id, stored, row.auth_blocked)
    return {"fetched": stored, "error": row.last_error, "blocked": bool(row.auth_blocked), "backfill": _backfill_state(row)}


def _backfill(session: Session, row: MailAccount, user_id: int | None, password: str, limit: int, timeout: int) -> int:
    if row.backfill_uid == 0:
        oldest = session.scalar(select(func.min(MailMessage.uid)).where(MailMessage.account_id == row.id, MailMessage.uid.is_not(None)))
        if oldest:
            row.backfill_uid = int(oldest)
        elif row.last_uid:
            row.backfill_uid = row.last_uid + 1
        else:
            row.backfill_uid = -1
    if row.backfill_uid <= 1:
        row.backfill_uid = -1
        return 0
    account_id = row.id
    host, port, use_ssl, username, folder, before = row.host, row.port, row.use_ssl, row.username, row.folder, row.backfill_uid
    session.commit()
    messages, error = imap_client.pull_older(host, port, use_ssl, username, password, folder, before, limit, timeout)
    row = session.get(MailAccount, account_id)
    if row is None:
        return 0
    if _is_auth(error):
        _block(session, row, error or "", password, user_id)
        return 0
    if error or not messages:
        if not error:
            row.backfill_uid = -1
        return 0
    moves: list[tuple[int, str, int | None]] = []
    stored = _store_batch(session, row, user_id, messages, notify=False, moves=moves)
    row.backfill_uid = min(uid for uid, _raw in messages)
    if row.backfill_uid <= 1:
        row.backfill_uid = -1
    session.commit()
    _run_moves(moves)
    return stored


def _store_batch(session, row: MailAccount, user_id, messages, notify: bool, moves: list | None = None) -> int:
    stored = 0
    pending = moves if moves is not None else []
    for uid, raw in messages:
        outcome, _found = _ingest(session, 0, user_id, raw, row, uid, row.folder, notify=notify, moves=pending)
        if outcome == "stored":
            stored += 1
    return stored


def _run_moves(moves: list[tuple[int, str, int | None]]) -> None:
    for message_id, folder_name, user_id in moves:
        try:
            with session_scope() as session:
                place_message(session, user_id, message_id, folder_name, True)
        except HTTPException:
            logger.info("mail file move failed message={}", message_id)


def _block(session: Session, row: MailAccount, error: str, password: str, user_id: int | None) -> None:
    row.auth_blocked = True
    row.last_error = _error_text(error or "Пароль не подошёл", password)
    row.last_checked_at = utcnow()
    row.updated_at = row.last_checked_at
    if not row.auth_notified:
        row.auth_notified = True
        enqueue(
            session,
            MAIL_AUTH_FAILED,
            {
                "title": "Почта: смените пароль",
                "subject": row.name,
                "error": row.last_error,
                "link": "/mail",
                "channels": ["browser", "telegram", "email"],
                "dedup_key": "mail-auth:" + str(row.id),
            },
            user_id=user_id,
        )
    session.flush()
    with log_scope("mail", "auth", user_id=user_id):
        logger.info("mail auth blocked account={}", row.id)


def _is_auth(error: str | None) -> bool:
    text_value = (error or "").casefold()
    if not text_value:
        return False
    if "папк" in text_value or "folder" in text_value:
        return False
    marks = ("authenticationfailed", "invalid credentials", "login failed", "invalid login", "authenticate", "bad password", "парол")
    return any(item in text_value for item in marks)


def _backfill_state(row: MailAccount) -> str:
    if row.backfill_uid < 0:
        return "done"
    return "continues"


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
    session.add(row)
    session.flush()
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


def _grouped_messages(session: Session, rows: list[MailMessage], project_id: int | None) -> list[dict]:
    groups: dict[str, list[MailMessage]] = {}
    order: list[str] = []
    for row in rows:
        key = _subject_key(row.subject, row.id, project_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    result = []
    for key in order:
        members = groups[key]
        latest = members[0]
        payload = _message_out(session, latest, full=False)
        cleaned = _clean_subject(latest.subject, project_id)
        if cleaned:
            payload["title"] = cleaned
        payload["thread_count"] = len(members)
        payload["thread_unread"] = sum(1 for item in members if not item.read)
        payload["thread_ids"] = [item.id for item in members]
        payload["attachment_count"] = sum(len(_meta(item)) for item in members)
        if payload["thread_unread"]:
            payload["read"] = False
        result.append(payload)
    return result


def _thread_out(session: Session, row: MailMessage, project_id: int) -> tuple[list[dict], int]:
    scope = project_id or None
    if not get_bool("mail", "threads.enabled", project_id=scope):
        return [], 0
    key = _subject_key(row.subject, row.id, project_id)
    limit = get_int("mail", "threads.scan_limit", project_id=scope)
    rows = list(
        session.scalars(
            select(MailMessage)
            .options(defer(MailMessage.html_body), defer(MailMessage.body))
            .order_by(MailMessage.received_at.desc(), MailMessage.id.desc())
            .limit(limit)
        ).all()
    )
    members = [item for item in rows if _subject_key(item.subject, item.id, project_id) == key]
    if project_id:
        rules = [rule for rule in _rules(session, project_id) if rule.enabled]
        members = [item for item in members if _row_matches(rules, item, project_id)]
    if len(members) < 2:
        return [], 0
    show = get_int("mail", "threads.show_limit", project_id=scope)
    items = [
        {
            "id": item.id,
            "title": item.subject or _title(item, project_id),
            "from_name": item.from_name,
            "from_addr": item.from_addr,
            "received_at": item.received_at.isoformat(),
            "read": bool(item.read),
            "archived": bool(item.archived),
        }
        for item in members[:show]
    ]
    return items, len(members)


def _subject_key(subject: str, message_id: int, project_id: int | None) -> str:
    scope = project_id or None
    if not get_bool("mail", "threads.enabled", project_id=scope):
        return "id:" + str(message_id)
    prefixes = _thread_prefixes()
    passes = get_int("mail", "threads.strip_passes", project_id=scope)
    folded = _fold_subject(subject, prefixes, passes)
    if not folded:
        if get_bool("mail", "threads.group_empty", project_id=scope):
            return "empty"
        return "id:" + str(message_id)
    return folded


def _clean_subject(subject: str, project_id: int | None) -> str:
    prefixes = _thread_prefixes()
    passes = get_int("mail", "threads.strip_passes", project_id=project_id or None)
    text_value = " ".join((subject or "").split())
    for _ in range(max(1, passes)):
        updated = _strip_prefix(text_value, prefixes)
        if updated == text_value:
            break
        text_value = updated
    return text_value.strip(" -")


def _fold_subject(subject: str, prefixes: list[str], passes: int) -> str:
    text_value = " ".join((subject or "").split())
    for _ in range(max(1, passes)):
        updated = _strip_prefix(text_value, prefixes)
        if updated == text_value:
            break
        text_value = updated
    return text_value.strip(" -").casefold()


def _thread_prefixes() -> list[str]:
    raw = get("mail", "threads.prefixes")
    prefixes = []
    if isinstance(raw, list):
        for item in raw:
            text_value = str(item or "").strip().casefold()
            if text_value and text_value not in prefixes:
                prefixes.append(text_value)
    prefixes.sort(key=len, reverse=True)
    return prefixes


def _strip_prefix(text_value: str, prefixes: list[str]) -> str:
    folded = text_value.casefold()
    for prefix in prefixes:
        if not folded.startswith(prefix):
            continue
        rest = text_value[len(prefix):]
        match = re.match(r"\s*(?:\[\d+\]|\(\d+\))?\s*[:\-]\s*", rest)
        if match:
            return rest[match.end():].strip()
    return text_value


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


def _matching_messages(session: Session, project_id: int, include_archived: bool) -> list[MailMessage]:
    statement = select(MailMessage)
    if not include_archived:
        statement = statement.where(MailMessage.archived.is_(False))
    scan = get_int("mail", "list.scan_limit", project_id=project_id)
    rows = list(session.scalars(statement.order_by(MailMessage.received_at.desc(), MailMessage.id.desc()).limit(scan)).all())
    rules = [rule for rule in _rules(session, project_id) if rule.enabled]
    return [row for row in rows if _row_matches(rules, row, project_id)]


def _row_matches(rules: list[MailRule], row: MailMessage, project_id: int) -> bool:
    if not rules:
        return False
    parsed = {
        "from_name": row.from_name or "",
        "from_addr": row.from_addr or "",
        "to_addr": row.to_addr or "",
        "subject": row.subject or "",
        "body": row.body or "",
    }
    casefold = get_bool("mail", "rules.casefold", project_id=project_id)
    return any(_matches(rule, parsed, casefold) for rule in rules)


def _matches(rule, parsed: dict, casefold: bool) -> bool:
    hay = _haystack(rule.field, parsed)
    needle = rule.value or ""
    if casefold:
        hay = hay.casefold()
        needle = needle.casefold()
    if rule.op == "equals":
        return hay.strip() == needle.strip()
    if rule.op == "not_contains":
        return needle not in hay
    return needle in hay


def _haystack(field: str, parsed: dict) -> str:
    if field == "from":
        return (parsed.get("from_name") or "") + " " + (parsed.get("from_addr") or "")
    if field == "to":
        return parsed.get("to_addr") or ""
    if field == "subject":
        return parsed.get("subject") or ""
    return parsed.get("body") or ""


def _message_out(session: Session, row: MailMessage, full: bool) -> dict:
    payload = {
        "id": row.id,
        "project_id": row.project_id,
        "account_id": row.account_id,
        "subject": row.subject,
        "title": _title(row, row.project_id),
        "from_name": row.from_name,
        "from_addr": row.from_addr,
        "to_addr": row.to_addr,
        "received_at": row.received_at.isoformat(),
        "read": bool(row.read),
        "archived": bool(row.archived),
        "attachment_count": len(_attachment_items(session, row)),
        "preview": _clip_text(row.body or "", get_int("mail", "list.preview_chars", project_id=row.project_id)),
        "tags": [],
    }
    if full:
        payload["body"] = row.body or ""
        payload["html"] = row.html_body or ""
        payload["attachments"] = _attachment_items(session, row)
        payload["events"] = [
            {
                "id": item.id,
                "summary": item.summary,
                "location": item.location,
                "starts_at": item.starts_at.isoformat(),
                "ends_at": item.ends_at.isoformat() if item.ends_at else None,
            }
            for item in session.scalars(select(MailEvent).where(MailEvent.message_id == row.id).order_by(MailEvent.starts_at)).all()
        ]
    return payload


def _attachment_items(session: Session, row: MailMessage) -> list[dict]:
    meta = _meta(row)
    saved = list(session.scalars(select(MailAttachment).where(MailAttachment.message_id == row.id)).all())
    by_name = {item.filename: item for item in saved}
    items = []
    for entry in meta:
        filename = entry.get("filename") or "файл"
        stored = by_name.get(filename)
        items.append(
            {
                "filename": filename,
                "mime": entry.get("mime") or "",
                "size": int(entry.get("size") or 0),
                "section": str(entry.get("section") or ""),
                "file_id": stored.file_id if stored is not None else None,
            }
        )
    return items


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


def _letter_matches_notify(session: Session, row: MailMessage) -> bool:
    if get_str("mail", "notify.mode") != "filter":
        return True
    rules = list(session.scalars(select(MailNotifyRule).order_by(MailNotifyRule.position, MailNotifyRule.id)).all())
    if not rules:
        return False
    hits = [_notify_rule_matches(session, rule, row) for rule in rules]
    if get_str("mail", "notify.match") == "all":
        return all(hits)
    return any(hits)


def _filed_matches_notify(session: Session, row: MailMessage) -> bool:
    if not get_bool("mail", "notify.gate_filed"):
        return True
    return _letter_matches_notify(session, row)


def _notify_rule_matches(session: Session, rule: MailNotifyRule, row: MailMessage) -> bool:
    if rule.field == "tag":
        return _tag_value_matches(session, row, rule.op, rule.value)
    parsed = {
        "from_name": row.from_name or "",
        "from_addr": row.from_addr or "",
        "to_addr": row.to_addr or "",
        "subject": row.subject or "",
        "body": row.body or "",
    }
    return _matches(rule, parsed, get_bool("mail", "rules.casefold"))


def _tag_value_matches(session: Session, row: MailMessage, op: str, value: str) -> bool:
    names, ids = _row_tag_keys(session, row)
    needle = (value or "").strip()
    folded = needle.casefold()
    blob = " ".join(sorted(names))
    if op == "equals":
        return folded in names or needle in ids
    if op == "not_contains":
        return folded not in blob and needle not in ids
    return folded in blob or needle in ids


def _row_tag_keys(session: Session, row: MailMessage) -> tuple[set[str], set[str]]:
    tags = list(session.scalars(select(MailTag).where(MailTag.enabled.is_(True))).all())
    if not tags:
        return set(), set()
    rules = list(session.scalars(select(MailTagRule).where(MailTagRule.tag_id.in_([tag.id for tag in tags]))).all())
    by_tag: dict[int, list[MailTagRule]] = {}
    for rule in rules:
        by_tag.setdefault(rule.tag_id, []).append(rule)
    pins = {(item.tag_id) for item in session.scalars(select(MailTagPin).where(MailTagPin.message_id == row.id)).all()}
    hides = {(item.tag_id) for item in session.scalars(select(MailTagHide).where(MailTagHide.message_id == row.id)).all()}
    names: set[str] = set()
    ids: set[str] = set()
    for tag in tags:
        if tag.id in hides:
            continue
        auto = bool(by_tag.get(tag.id)) and all(_tag_rule_matches(item, row) for item in by_tag[tag.id])
        if auto or tag.id in pins:
            names.add((tag.name or "").casefold())
            ids.add(str(tag.id))
    return names, ids


def _notify_rule_out(session: Session, rule: MailNotifyRule) -> dict:
    shown = rule.value
    if rule.field == "tag" and str(rule.value).isdigit():
        tag = session.get(MailTag, int(rule.value))
        shown = tag.name if tag is not None else "хештег удалён"
    field_label = _label(0, "notify.fields", rule.field)
    op_label = _label(0, "notify.ops", rule.op)
    return {
        "id": rule.id,
        "field": rule.field,
        "op": rule.op,
        "value": rule.value,
        "text": field_label + " " + op_label + " «" + shown + "»",
    }


def _notify_pair(field: str, op: str) -> tuple[str, str]:
    field_code = _choice(field, 0, "notify.fields", "Поле не из списка")
    op_code = _choice(op, 0, "notify.ops", "Операция не из списка")
    if field_code == "tag" and op_code not in ("equals", "contains", "not_contains"):
        raise HTTPException(status_code=400, detail="Для хештега нужно равно, содержит или не содержит")
    return field_code, op_code


def _notify_tag_value(session: Session, raw: str) -> str:
    if raw.isdigit():
        tag = session.get(MailTag, int(raw))
        if tag is None:
            raise HTTPException(status_code=400, detail="Хештег не найден")
        return str(tag.id)
    name = _clean(raw, "tags.name.max_length", "Укажите хештег")
    tag = session.scalars(select(MailTag).where(MailTag.name == name)).first()
    if tag is None:
        raise HTTPException(status_code=400, detail="Такого хештега нет. Сначала создайте его на вкладке «Хештеги»")
    return str(tag.id)


def _attach_tags(session: Session, messages: list[dict]) -> None:
    ids: list[int] = []
    for item in messages:
        ids.extend(item.get("thread_ids") or [item.get("id")])
    ids = [item for item in ids if item]
    if not ids:
        return
    tags = list(session.scalars(select(MailTag).where(MailTag.enabled.is_(True)).order_by(MailTag.position, MailTag.id)).all())
    rules = list(session.scalars(select(MailTagRule).where(MailTagRule.tag_id.in_([tag.id for tag in tags] or [0]))).all()) if tags else []
    by_tag: dict[int, list[MailTagRule]] = {}
    for rule in rules:
        by_tag.setdefault(rule.tag_id, []).append(rule)
    pins = session.scalars(select(MailTagPin).where(MailTagPin.message_id.in_(ids))).all()
    hides = session.scalars(select(MailTagHide).where(MailTagHide.message_id.in_(ids))).all()
    pin_set = {(item.message_id, item.tag_id) for item in pins}
    hide_set = {(item.message_id, item.tag_id) for item in hides}
    rows = {row.id: row for row in session.scalars(select(MailMessage).where(MailMessage.id.in_(ids))).all()}

    def chosen_for(message_id: int) -> list[dict]:
        row = rows.get(message_id)
        if row is None:
            return []
        chosen = []
        for tag in tags:
            auto = bool(by_tag.get(tag.id)) and all(_tag_rule_matches(rule, row) for rule in by_tag[tag.id])
            pinned = (row.id, tag.id) in pin_set
            hidden = (row.id, tag.id) in hide_set
            if hidden:
                continue
            if auto or pinned:
                chosen.append({"id": tag.id, "name": tag.name, "color": tag.color})
        return chosen

    for message in messages:
        member_ids = message.get("thread_ids") or [message.get("id")]
        seen: set[int] = set()
        chosen = []
        for member_id in member_ids:
            for tag in chosen_for(member_id):
                if tag["id"] in seen:
                    continue
                seen.add(tag["id"])
                chosen.append(tag)
        message["tags"] = chosen
        message.pop("thread_ids", None)


def _tag_rule_matches(rule: MailTagRule, row: MailMessage) -> bool:
    if rule.field == "received":
        local = row.received_at.astimezone(_zone()).date()
        try:
            day = datetime.strptime((rule.value or "")[:10], "%Y-%m-%d").date()
        except ValueError:
            return False
        if rule.op == "before":
            return local < day
        if rule.op == "after":
            return local > day
        return local == day
    parsed = {
        "from_name": row.from_name or "",
        "from_addr": row.from_addr or "",
        "to_addr": row.to_addr or "",
        "subject": row.subject or "",
        "body": row.body or "",
    }
    return _matches(rule, parsed, True)


def _tag_catalog(session: Session) -> list[dict]:
    tags = session.scalars(select(MailTag).order_by(MailTag.position, MailTag.id)).all()
    return [_tag_out(session, tag) for tag in tags]


def _tag_out(session: Session, tag: MailTag) -> dict:
    rules = session.scalars(select(MailTagRule).where(MailTagRule.tag_id == tag.id).order_by(MailTagRule.id)).all()
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "enabled": bool(tag.enabled),
        "rules": [{"field": rule.field, "op": rule.op, "value": rule.value} for rule in rules],
    }


def _tag_color(value: str) -> str:
    text_value = (value or "").strip()
    if not text_value:
        text_value = get_str("mail", "tags.default_color")
    if len(text_value) == 4 and text_value.startswith("#"):
        text_value = "#" + "".join(ch * 2 for ch in text_value[1:])
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", text_value):
        raise HTTPException(status_code=400, detail="Цвет задаётся как HEX, например #3a6ea5")
    return text_value.lower()


def _tag_pair(field: str, op: str) -> tuple[str, str]:
    field_code = _choice(field, 0, "tags.fields", "Поле не из списка")
    op_code = _choice(op, 0, "tags.ops", "Операция не из списка")
    date_ops = {"before", "after", "on"}
    if field_code == "received" and op_code not in date_ops:
        raise HTTPException(status_code=400, detail="Для даты нужны условия раньше, позже или в этот день")
    if field_code != "received" and op_code in date_ops:
        raise HTTPException(status_code=400, detail="Дата сравнивается только с полем даты")
    return field_code, op_code


def _account_out(row: MailAccount) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "host": row.host,
        "port": row.port,
        "use_ssl": bool(row.use_ssl),
        "username": row.username,
        "folder": row.folder,
        "enabled": bool(row.enabled),
        "has_password": bool(row.password_enc),
        "last_uid": row.last_uid,
        "backfill_uid": row.backfill_uid,
        "auth_blocked": bool(row.auth_blocked),
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
        "last_error": row.last_error or "",
    }


def _rule_out(row: MailRule, project_id: int) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "enabled": bool(row.enabled),
        "position": row.position,
        "field": row.field,
        "field_label": _label(project_id, "rules.fields", row.field),
        "op": row.op,
        "op_label": _label(project_id, "rules.ops", row.op),
        "value": row.value,
        "action": row.action,
        "action_label": _label(project_id, "rules.actions", row.action),
    }


def _sync_info() -> dict:
    return {
        "automatic": get_bool("mail", "job.enabled"),
        "every_seconds": get_int("mail", "job.seconds"),
        "batch_size": get_int("mail", "fetch.batch_size"),
        "batches_per_run": get_int("mail", "fetch.batches_per_run"),
    }


def _meta(row: MailMessage) -> list[dict]:
    raw = row.attachments_json or ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _search_blob(row: MailMessage) -> str:
    return "\n".join([row.subject or "", row.from_name or "", row.from_addr or "", row.to_addr or "", row.body or ""])


def _title(row: MailMessage, project_id: int) -> str:
    text_value = (row.subject or "").strip()
    if text_value:
        return text_value
    return get_str("mail", "message.empty_subject", project_id=project_id or None) or "(без темы)"


def _snippet(blob: str, needle: str, width: int) -> str:
    folded = blob.casefold()
    at = folded.find(needle.casefold())
    if at < 0:
        return _clip_text(blob, width)
    start = max(0, at - width // 3)
    return _clip_text(blob[start:], width)


def _clip_text(value: str, limit: int) -> str:
    text_value = " ".join((value or "").split())
    if len(text_value) <= limit:
        return text_value
    return text_value[:limit].rstrip() + "…"


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


def _limits() -> dict:
    encodings = get("mail", "body.encodings")
    if not isinstance(encodings, list):
        encodings = ["utf-8"]
    return {
        "max_bytes": get_int("mail", "message.max_bytes"),
        "subject": get_int("mail", "message.subject.max_length"),
        "address": get_int("mail", "message.address.max_length"),
        "body": get_int("mail", "message.body.max_chars"),
        "html": get_int("mail", "message.html.max_chars"),
        "events": get_int("mail", "events.per_message"),
        "zone": get_str("core", "ui.timezone") or "UTC",
        "encodings": [str(item) for item in encodings if str(item).strip()],
    }


def _choices(project_id: int, key: str) -> list[dict]:
    raw = get("mail", key, project_id=project_id or None)
    items = []
    if not isinstance(raw, list):
        return items
    for item in raw:
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            code = str(item["id"]).strip()
            items.append({"id": code, "label": str(item.get("label") or code)})
        elif isinstance(item, str) and item.strip():
            items.append({"id": item.strip(), "label": item.strip()})
    return items


def _choice(value: str, project_id: int, key: str, error: str) -> str:
    code = (value or "").strip()
    known = {item["id"] for item in _choices(project_id, key)}
    if not code or code not in known:
        raise HTTPException(status_code=400, detail=error)
    return code


def _label(project_id: int, key: str, code: str) -> str:
    for item in _choices(project_id, key):
        if item["id"] == code:
            return item["label"]
    return code


def _clean(value: str, key: str, empty: str) -> str:
    text_value = (value or "").strip()
    if not text_value:
        raise HTTPException(status_code=400, detail=empty)
    limit = get_int("mail", key)
    if len(text_value) > limit:
        raise HTTPException(status_code=400, detail="Длиннее " + str(limit) + " символов")
    return text_value


def _clip(value: str, key: str) -> str:
    text_value = value or ""
    limit = get_int("mail", key)
    if len(text_value) > limit:
        return text_value[:limit]
    return text_value


def _password(value: str, required: bool) -> str:
    text_value = value or ""
    if required and not text_value:
        raise HTTPException(status_code=400, detail="Укажите пароль")
    limit = get_int("mail", "account.password.max_length")
    if len(text_value) > limit:
        raise HTTPException(status_code=400, detail="Пароль длиннее " + str(limit) + " символов")
    return text_value


def _pack(password: str) -> str:
    try:
        return crypto.encrypt(password)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Не удалось сохранить пароль") from exc


def _unpack(row: MailAccount) -> str:
    if not row.password_enc:
        return ""
    try:
        return crypto.decrypt(row.password_enc)
    except ValueError:
        return ""


def _port(value, project_id: int) -> int:
    if value is None or value == "":
        return get_int("mail", "imap.default_port", project_id=project_id or None)
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Порт должен быть числом") from exc
    if port < 1 or port > 65535:
        raise HTTPException(status_code=400, detail="Порт вне диапазона")
    return port


def _ssl(value, project_id: int) -> bool:
    if value is None:
        return get_bool("mail", "imap.default_ssl", project_id=project_id or None)
    return bool(value)


def _folder(value, project_id: int) -> str:
    text_value = (value or "").strip()
    if not text_value:
        text_value = get_str("mail", "imap.default_folder", project_id=project_id or None) or "INBOX"
    return _clip(text_value, "account.folder.max_length") or "INBOX"


def _timeout(project_id: int) -> int:
    return get_int("mail", "imap.timeout_seconds", project_id=project_id or None)


def _lookback_token(project_id: int) -> str:
    days = get_int("mail", "fetch.lookback_days", project_id=project_id or None)
    days = min(30, max(1, days))
    moment = datetime.now(_zone()) - timedelta(days=days - 1)
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{moment.day:02d}-{months[moment.month - 1]}-{moment.year}"


def _error_text(error: str, password: str) -> str:
    text_value = (error or "").replace(password, "***") if password else (error or "")
    limit = get_int("mail", "account.error_max_chars")
    return text_value[:limit]


def _format_when(value) -> str:
    if not isinstance(value, datetime):
        return ""
    local = value.astimezone(_zone())
    pattern = get_str("core", "ui.date_format") or "YYYY-MM-DD HH:mm"
    return (
        pattern.replace("YYYY", f"{local.year:04d}")
        .replace("MM", f"{local.month:02d}")
        .replace("DD", f"{local.day:02d}")
        .replace("HH", f"{local.hour:02d}")
        .replace("mm", f"{local.minute:02d}")
    )


def _zone():
    name = get_str("core", "ui.timezone") or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc
