"""Хелперы настроек, валидации, паролей и времени.

Нижний слой пакета: не импортирует другие файлы ``service/``,
поэтому от него зависит всё остальное.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.core.settings_store import get, get_bool, get_int, get_str
from app.modules.mail import crypto
from app.modules.mail.models import MailAccount


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


def _is_auth(error: str | None) -> bool:
    text_value = (error or "").casefold()
    if not text_value:
        return False
    if "папк" in text_value or "folder" in text_value:
        return False
    marks = ("authenticationfailed", "invalid credentials", "login failed", "invalid login", "authenticate", "bad password", "парол")
    return any(item in text_value for item in marks)
