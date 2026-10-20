from __future__ import annotations

import socket
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_catalog import RDP_CREATED, RDP_DELETED, RDP_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int
from app.core.versioning import check_version
from app.modules.projects.service import touch_project
from app.modules.rdp.models import RdpConnection
from app.modules.secrets.crypto import decrypt as secret_decrypt
from app.modules.secrets.models import Secret

# Порт RDP по умолчанию; в .rdp пишется только при отличии от него.
STANDARD_PORT = 3389


def list_connections(session: Session, project_id: int, include_archived: bool, query: str) -> dict:
    needle = (query or "").strip().casefold()
    scan = get_int("rdp", "list.scan_limit", project_id=project_id)
    limit = get_int("rdp", "list.limit", project_id=project_id)
    statement = select(RdpConnection).where(
        RdpConnection.project_id == project_id,
        # Записи из корзины в рабочем списке не показываем.
        RdpConnection.deleted_at.is_(None),
    )
    if not include_archived:
        statement = statement.where(RdpConnection.archived.is_(False))
    rows = list(session.scalars(statement.order_by(RdpConnection.updated_at.desc(), RdpConnection.id.desc()).limit(scan)).all())
    if needle:
        rows = [row for row in rows if needle in (row.name or "").casefold() or needle in (row.host or "").casefold()]
    rows = rows[:limit]
    titles = _secret_titles(session, [row.secret_id for row in rows])
    return {"items": [_public(row, titles.get(row.secret_id)) for row in rows]}


def create_connection(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    now = utcnow()
    row = RdpConnection(
        project_id=project_id,
        name=_clean_name(fields.get("name") or ""),
        host=_clean_host(fields.get("host") or ""),
        port=_clean_port(fields.get("port"), project_id),
        username=_clean_text(fields.get("username") or "", "username.max_length", strip=True),
        domain=_clean_text(fields.get("domain") or "", "domain.max_length", strip=True),
        secret_id=_secret_id(session, project_id, fields.get("secret_id")),
        note=_clean_text(fields.get("note") or "", "note.max_length", strip=False),
        archived=False,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("rdp", "create", user_id=user_id):
        logger.info("rdp connection created id={} host={}", row.id, row.host)
    enqueue(
        session,
        RDP_CREATED,
        {"title": row.name, "project_id": project_id, "link": "/projects/" + str(project_id) + "/rdp"},
        user_id=user_id,
    )
    return _public(row, _secret_titles(session, [row.secret_id]).get(row.secret_id))


def get_connection(session: Session, project_id: int, rdp_id: int) -> dict:
    row = _row(session, project_id, rdp_id)
    return _public(row, _secret_titles(session, [row.secret_id]).get(row.secret_id))


def update_connection(session: Session, project_id: int, user_id: int, rdp_id: int, fields: dict) -> dict:
    row = _row(session, project_id, rdp_id)
    check_version(fields, row.updated_at, "Подключение")
    if "name" in fields and fields["name"] is not None:
        row.name = _clean_name(fields["name"])
    if "host" in fields and fields["host"] is not None:
        row.host = _clean_host(fields["host"])
    if "port" in fields and fields["port"] is not None:
        row.port = _clean_port(fields["port"], project_id)
    if "username" in fields and fields["username"] is not None:
        row.username = _clean_text(fields["username"], "username.max_length", strip=True)
    if "domain" in fields and fields["domain"] is not None:
        row.domain = _clean_text(fields["domain"], "domain.max_length", strip=True)
    if "secret_id" in fields:
        row.secret_id = _secret_id(session, project_id, fields.get("secret_id"))
    if "note" in fields and fields["note"] is not None:
        row.note = _clean_text(fields["note"], "note.max_length", strip=False)
    if "archived" in fields and fields["archived"] is not None:
        row.archived = bool(fields["archived"])
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        RDP_UPDATED,
        {"title": row.name, "project_id": project_id, "link": "/projects/" + str(project_id) + "/rdp"},
        user_id=user_id,
    )
    with log_scope("rdp", "update", user_id=user_id):
        logger.info("rdp connection updated id={} archived={}", row.id, row.archived)
    return _public(row, _secret_titles(session, [row.secret_id]).get(row.secret_id))


def delete_connection(session: Session, project_id: int, user_id: int, rdp_id: int) -> dict:
    """Мягкое удаление: запись уходит в корзину и восстановима (патч N).

    Возвращает краткое описание для ответа API (событие и лог — как раньше).
    """
    row = _row(session, project_id, rdp_id)
    row.deleted_at = utcnow()
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        RDP_DELETED,
        {"title": "Подключение удалено", "subject": row.name, "project_id": project_id, "link": "/projects/" + str(project_id) + "/rdp"},
        user_id=user_id,
    )
    with log_scope("rdp", "delete", user_id=user_id):
        logger.info("rdp connection deleted id={}", rdp_id)
    return {"id": row.id, "deleted_at": row.deleted_at.isoformat(), "title": row.name}


def purge_connection(session: Session, project_id: int, user_id: int, rdp_id: int) -> None:
    """Настоящее удаление из корзины — окончательное."""
    row = _row(session, project_id, rdp_id, in_trash=True)
    session.delete(row)
    touch_project(session, project_id)
    session.flush()
    with log_scope("rdp", "purge", user_id=user_id):
        logger.info("rdp connection purged id={}", rdp_id)


def restore_connection(session: Session, project_id: int, user_id: int, rdp_id: int) -> dict:
    row = _row(session, project_id, rdp_id, in_trash=True)
    row.deleted_at = None
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        RDP_UPDATED,
        {"title": "Подключение восстановлено", "subject": row.name, "project_id": project_id, "link": "/projects/" + str(project_id) + "/rdp"},
        user_id=user_id,
    )
    with log_scope("rdp", "restore", user_id=user_id):
        logger.info("rdp connection restored id={}", rdp_id)
    return _public(row, _secret_titles(session, [row.secret_id]).get(row.secret_id))


def connection_file(session: Session, project_id: int, user_id: int, rdp_id: int) -> dict:
    """Собирает .rdp для подключения. Пароль не хранится и не пишется:
    mstsc спросит его сам (prompt for credentials), см. путь «А».

    Логин берётся из записи, а если поле пустое и указан секрет — из
    хранилища (расшифровывается только логин, значение остаётся на сервере).
    """
    row = _row(session, project_id, rdp_id)
    address = row.host if row.port == STANDARD_PORT else row.host + ":" + str(row.port)
    username = row.username or _secret_username(session, row.secret_id)
    lines = [
        "screen mode id:i:1",
        "use multimon:i:0",
        "smart sizing:i:1",
        "full address:s:" + address,
    ]
    if username:
        lines.append("username:s:" + username)
    if row.domain:
        lines.append("domain:s:" + row.domain)
    lines.append("prompt for credentials:i:1")
    lines.append("autoreconnection enabled:i:1")
    with log_scope("rdp", "file", user_id=user_id):
        logger.info("rdp file built id={} host={}", row.id, row.host)
    return {"filename": _filename(row.name), "content": "\r\n".join(lines) + "\r\n"}


def ping_connection(session: Session, project_id: int, user_id: int, rdp_id: int) -> dict:
    """TCP-проверка доступности: коннект к host:port с таймаутом.

    Возвращает {ok, latency_ms, error}. Самохостинг-контекст: сервер
    проверяет ровно тот адрес, что уже сохранён в подключении.
    """
    row = _row(session, project_id, rdp_id)
    timeout = get_int("rdp", "ping.timeout_seconds", project_id=project_id)
    started = time.monotonic()
    error = ""
    try:
        with socket.create_connection((row.host, row.port), timeout=timeout):
            pass
    except OSError as exc:
        error = _ping_error(exc)
    latency = int((time.monotonic() - started) * 1000)
    ok = not error
    with log_scope("rdp", "ping", user_id=user_id):
        logger.info("rdp ping id={} host={} ok={} latency_ms={}", row.id, row.host, ok, latency if ok else -1)
    return {"ok": ok, "latency_ms": latency if ok else None, "error": error}


def search_provider(session: Session, project_id: int, user_id: int | None, query: str, limit: int) -> list[dict]:
    needle = (query or "").casefold()
    statement = select(RdpConnection).where(
        RdpConnection.project_id == project_id,
        RdpConnection.deleted_at.is_(None),
    )
    if not get_bool("rdp", "search.include_archived", project_id=project_id):
        statement = statement.where(RdpConnection.archived.is_(False))
    rows = session.scalars(statement.order_by(RdpConnection.updated_at.desc(), RdpConnection.id.desc())).all()
    found = []
    for row in rows:
        if needle in (row.name or "").casefold() or needle in (row.host or "").casefold():
            found.append({"id": row.id, "title": row.name})
        if len(found) >= limit:
            break
    return found


def _row(session: Session, project_id: int, rdp_id: int, in_trash: bool = False) -> RdpConnection:
    row = session.get(RdpConnection, rdp_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Подключение не найдено")
    if in_trash and row.deleted_at is None:
        raise HTTPException(status_code=404, detail="Подключение не в корзине")
    if not in_trash and row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Подключение удалено в корзину")
    return row


def _secret_id(session: Session, project_id: int, value) -> int | None:
    """Валидация связки: секрет того же проекта, не в корзине; None очищает."""
    if value is None or value == 0 or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=400, detail="Секрет указан некорректно")
    row = session.get(Secret, value)
    if row is None or row.project_id != project_id or row.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Секрет не найден в этом проекте")
    return row.id


def _secret_titles(session: Session, secret_ids: list[int | None]) -> dict[int, str]:
    ids = [value for value in secret_ids if value]
    if not ids:
        return {}
    rows = session.execute(select(Secret.id, Secret.title).where(Secret.id.in_(ids))).all()
    return {row_id: title for row_id, title in rows}


def _secret_username(session: Session, secret_id: int | None) -> str:
    if not secret_id:
        return ""
    row = session.get(Secret, secret_id)
    if row is None or not row.username_enc:
        return ""
    try:
        return secret_decrypt(row.username_enc).strip()
    except Exception:
        with log_scope("rdp", "secret.username"):
            logger.warning("не удалось прочитать логин секрета id={}", secret_id)
        return ""


def _ping_error(exc: OSError) -> str:
    text = str(exc) or exc.__class__.__name__
    return text[:200]


def _public(row: RdpConnection, secret_title: str | None = None) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "host": row.host,
        "port": row.port,
        "username": row.username or "",
        "domain": row.domain or "",
        "secret_id": row.secret_id,
        "secret_title": secret_title or "",
        "note": row.note or "",
        "archived": bool(row.archived),
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _filename(name: str) -> str:
    safe = "".join(char if char.isascii() and (char.isalnum() or char in "-_") else "_" for char in (name or "").strip())
    safe = safe.strip("_") or "connection"
    return safe[:120] + ".rdp"


def _clean_name(value: str) -> str:
    text = (value or "").strip()
    limit = get_int("rdp", "name.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Укажите название")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Название длиннее " + str(limit) + " символов")
    return text


def _clean_host(value: str) -> str:
    text = (value or "").strip()
    limit = get_int("rdp", "host.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Укажите адрес сервера")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Адрес длиннее " + str(limit) + " символов")
    if any(char.isspace() for char in text):
        raise HTTPException(status_code=400, detail="Адрес не должен содержать пробелов")
    if ":" in text:
        raise HTTPException(status_code=400, detail="Порт укажите отдельным полем, без двоеточия в адресе")
    return text


def _clean_port(value, project_id: int) -> int:
    port = get_int("rdp", "port.default", project_id=project_id) if value is None else value
    if not isinstance(port, int) or isinstance(port, bool) or port < 1 or port > 65535:
        raise HTTPException(status_code=400, detail="Порт — число от 1 до 65535")
    return port


def _clean_text(value: str, key: str, strip: bool) -> str:
    text = value or ""
    if strip:
        text = text.strip()
    limit = get_int("rdp", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Текст длиннее " + str(limit) + " символов")
    return text
