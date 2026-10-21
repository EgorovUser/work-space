"""Ящики: CRUD, проверка логина, забор писем с бэкфиллом, перенос на сервере.

Сюда же относится ``place_message`` — операция с письмом через IMAP-аккаунт
(копия/перенос в папку) и ``_run_moves`` — отложенные переносы после fetch.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import session_scope, utcnow
from app.core import counters
from app.core.events_bus import publish as _bus_publish
from app.core.events_catalog import MAIL_AUTH_FAILED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int
from app.modules.mail import imap_client, parse
from app.modules.mail.models import MailAccount, MailMessage
from app.modules.mail.service._queries import _account, _account_any
from app.modules.mail.service._serialize import _account_out
from app.modules.mail.service._settings import (
    _clean,
    _clip,
    _error_text,
    _folder,
    _is_auth,
    _limits,
    _lookback_token,
    _pack,
    _password,
    _port,
    _ssl,
    _timeout,
    _unpack,
)
from app.modules.mail.service.ingest import _ingest
from app.modules.projects.service import touch_project


def publish_event(event_type, payload=None, user_id=None):
    """Сигнал шины + сброс кеша счётчиков (патч T): забор писем меняет числа бейджей."""
    _bus_publish(event_type, payload, user_id)
    counters.invalidate()


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
    name = row.name
    result = _fetch_row(session, row, user_id)
    # Открытые вкладки узнают о письмах сразу, не дожидаясь своего опроса.
    fetched = int(result.get("fetched") or 0)
    if fetched:
        publish_event("mail.sync", {"account_id": account_id, "account": name, "fetched": fetched})
        publish_event("mail.changed")
    return result


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
        result: dict = {}
        name = ""
        try:
            with session_scope() as session:
                row = session.get(MailAccount, account_id)
                if row is not None and row.enabled and not row.auth_blocked:
                    name = row.name
                    result = _fetch_row(session, row, None)
        except Exception:
            logger.exception("mail poll failed account={}", account_id)
            continue
        # session_scope уже закоммитил: открытые вкладки могут пересчитывать счётчики.
        fetched = int(result.get("fetched") or 0)
        if fetched:
            publish_event("mail.sync", {"account_id": account_id, "account": name, "fetched": fetched})
            publish_event("mail.changed")


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
                "channels": ["browser", "os", "telegram", "email"],
                "dedup_key": "mail-auth:" + str(row.id),
            },
            user_id=user_id,
        )
    session.flush()
    with log_scope("mail", "auth", user_id=user_id):
        logger.info("mail auth blocked account={}", row.id)


def _backfill_state(row: MailAccount) -> str:
    if row.backfill_uid < 0:
        return "done"
    return "continues"
