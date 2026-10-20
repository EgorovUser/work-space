"""Сборка dict-ответов и исходящих сообщений: лента, письмо боту, текст события."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import get_str
from app.modules.notifications.models import Notification, NotificationDelivery
from app.modules.notifications.service._settings import _clip, _label


def _compose(event_type: str, payload: dict) -> tuple[str, str, str]:
    label = _label("events", event_type)
    title = str(payload.get("title") or payload.get("subject") or label or event_type)
    lines = [label] if label and label != title else []
    subject = str(payload.get("subject") or "")
    if subject and subject != title:
        lines.append(subject)
    if payload.get("when"):
        lines.append(str(payload["when"]))
    if payload.get("location"):
        lines.append(str(payload["location"]))
    if "days_left" in payload and isinstance(payload.get("days_left"), int):
        days = payload["days_left"]
        if days < 0:
            lines.append("Просрочено на " + str(-days) + " дн.")
        else:
            lines.append("До срока " + str(days) + " дн.")
    if payload.get("error"):
        lines.append(str(payload["error"]))
    return _clip(title, "title.max_length"), _clip("\n".join(lines), "body.max_length"), _link(payload)


def _link(payload: dict) -> str:
    if payload.get("link"):
        return str(payload["link"])
    project_id = payload.get("project_id")
    if payload.get("task_id") and project_id:
        return "/projects/" + str(project_id) + "/tasks/" + str(payload["task_id"])
    if payload.get("document_id") and project_id:
        return "/projects/" + str(project_id) + "/documents/" + str(payload["document_id"])
    if payload.get("message_id") and project_id:
        return "/projects/" + str(project_id) + "/mail/" + str(payload["message_id"])
    if payload.get("module") and not project_id:
        return "/system"
    return ""


def _outgoing(note: Notification) -> str:
    parts = [note.title]
    if note.body:
        parts.append(note.body)
    if note.link:
        base = get_str("notifications", "link.base_url", user_id=note.user_id).rstrip("/")
        parts.append(base + note.link if base else note.link)
    return _clip("\n".join(parts), "message.max_chars")


def _out(session: Session, row: Notification, user_id: int) -> dict:
    deliveries = session.scalars(
        select(NotificationDelivery).where(NotificationDelivery.notification_id == row.id)
    ).all()
    return {
        "id": row.id,
        "event_type": row.event_type,
        "event_label": _label("events", row.event_type),
        "title": row.title,
        "body": row.body or "",
        "link": row.link or "",
        "read": bool(row.read),
        "created_at": row.created_at.isoformat(),
        "deliveries": [
            {
                "channel": item.channel,
                "channel_label": _label("channels", item.channel),
                "status": item.status,
                "status_label": _label("statuses", item.status),
                "attempts": item.attempts or 0,
                "last_error": item.last_error or "",
            }
            for item in deliveries
        ],
    }
