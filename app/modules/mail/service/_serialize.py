"""Построение dict-ответов: ящики, правила, письма, синхронизация, сниппеты."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import get_bool, get_int, get_str
from app.modules.mail.models import (
    MailAccount,
    MailAttachment,
    MailEvent,
    MailMessage,
    MailRule,
)
from app.modules.mail.service._settings import _label


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
