from __future__ import annotations

from datetime import timedelta
import time

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.db import session_scope, utcnow
from app.core.events_bus import publish as publish_event
from app.core.events_catalog import ALL_EVENTS
from app.core.logging import log_scope, logger
from app.core.models import User
from app.core.outbox import EventMessage
from app.core.settings_store import get, get_bool, get_int, get_str
from app.modules.notifications import channels
from app.modules.notifications.models import Notification, NotificationDelivery


def handle(message: EventMessage) -> None:
    delivery_ids: list[int] = []
    with session_scope() as session:
        already = session.scalars(
            select(Notification.id).where(Notification.outbox_id == message.id)
        ).first()
        if already is not None:
            return
        dedup = str((message.payload or {}).get("dedup_key") or "").strip() or None
        title, body, link = _compose(message.event_type, message.payload or {})
        created = 0
        for user in _recipients(session, message):
            if get_bool("notifications", "audience.skip_actor") and message.user_id and user.id == message.user_id:
                continue
            if dedup and _dedup_exists(session, user.id, dedup):
                continue
            flags = _flags(user.id, message.event_type)
            forced = (message.payload or {}).get("channels")
            if isinstance(forced, list) and forced:
                flags = {item["id"]: item["id"] in forced for item in _choices("channels")}
            if not any(flags.values()):
                continue
            row = Notification(
                user_id=user.id,
                outbox_id=message.id,
                event_type=message.event_type,
                dedup_key=dedup,
                title=title,
                body=body,
                link=link,
                show_browser=bool(flags.get("browser")),
                read=False,
                created_at=utcnow(),
            )
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                session.expunge(row)
                continue
            for channel, enabled in flags.items():
                if channel == "browser" or not enabled:
                    continue
                delivery = NotificationDelivery(
                    notification_id=row.id,
                    channel=channel,
                    status="pending",
                    attempts=0,
                    last_error="",
                    next_attempt_at=utcnow(),
                    updated_at=utcnow(),
                )
                session.add(delivery)
                session.flush()
                delivery_ids.append(delivery.id)
            created += 1
        if created:
            with log_scope("notifications", "create", user_id=message.user_id):
                logger.info("notifications created event={} count={}", message.event_type, created)
            # Открытые вкладки пересчитают свой счётчик уведомлений сразу.
            publish_event("notifications.changed")
    for delivery_id in delivery_ids:
        send_delivery(delivery_id)


def deliver_due() -> None:
    if not get_bool("notifications", "job.enabled"):
        return
    now = utcnow()
    stale_before = now - timedelta(seconds=get_int("notifications", "delivery.stale_seconds"))
    max_attempts = get_int("notifications", "delivery.max_attempts")
    with session_scope() as session:
        stuck = session.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.status == "sending",
                NotificationDelivery.updated_at < stale_before,
            )
        ).all()
        for row in stuck:
            row.status = "pending"
            row.updated_at = now
        due = session.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.status.in_(("pending", "failed")),
                NotificationDelivery.next_attempt_at <= now,
            )
        ).all()
        ids = [row.id for row in due if row.status == "pending" or (row.attempts or 0) < max_attempts]
    for delivery_id in ids:
        try:
            send_delivery(delivery_id)
        except Exception:
            logger.exception("delivery crashed id={}", delivery_id)
    for delivery_id in _catchup_ids():
        try:
            send_delivery(delivery_id)
        except Exception:
            logger.exception("delivery catchup crashed id={}", delivery_id)


def _catchup_ids() -> list[int]:
    if not get_bool("notifications", "delivery.catchup"):
        return []
    since = utcnow() - timedelta(hours=get_int("notifications", "delivery.catchup_hours"))
    batch = get_int("notifications", "delivery.catchup_batch")
    created: list[int] = []
    with session_scope() as session:
        notes = session.scalars(
            select(Notification).where(Notification.created_at >= since).order_by(Notification.id.desc())
        ).all()
        for note in notes:
            if len(created) >= batch:
                break
            flags = _flags(note.user_id, note.event_type)
            existing = {
                row.channel
                for row in session.scalars(
                    select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id)
                ).all()
            }
            for channel, enabled in flags.items():
                if channel == "browser" or not enabled or channel in existing:
                    continue
                delivery = NotificationDelivery(
                    notification_id=note.id,
                    channel=channel,
                    status="pending",
                    attempts=0,
                    last_error="",
                    next_attempt_at=utcnow(),
                    updated_at=utcnow(),
                )
                try:
                    with session.begin_nested():
                        session.add(delivery)
                        session.flush()
                except IntegrityError:
                    session.expunge(delivery)
                    continue
                created.append(delivery.id)
                existing.add(channel)
                if len(created) >= batch:
                    break
    if created:
        logger.info("delivery catchup count={}", len(created))
    return created


def send_delivery(delivery_id: int) -> None:
    with session_scope() as session:
        row = session.get(NotificationDelivery, delivery_id)
        if row is None or row.status not in ("pending", "failed"):
            return
        limit = get_int("notifications", "delivery.max_attempts")
        if row.status == "failed" and (row.attempts or 0) >= limit:
            return
        claim = session.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.status.in_(("pending", "failed")),
            )
            .values(status="sending", updated_at=utcnow())
        )
        if claim.rowcount != 1:
            return
        note = session.get(Notification, row.notification_id)
        if note is None:
            row.status = "skipped"
            row.last_error = "Уведомление удалено"
            row.updated_at = utcnow()
            return
        channel = row.channel
        user_id = note.user_id
        subject = note.title
        text = _outgoing(note)
    if channel == "telegram":
        status, error = channels.send_telegram(user_id, text)
    elif channel == "email":
        status, error = channels.send_email(user_id, subject, text)
    else:
        status, error = "skipped", "Неизвестный канал"
    _finish(delivery_id, status, error, channel)


def list_notifications(session: Session, user_id: int, unread_only: bool) -> dict:
    limit = get_int("notifications", "list.limit", user_id=user_id)
    statement = select(Notification).where(Notification.user_id == user_id, Notification.show_browser.is_(True))
    if unread_only:
        statement = statement.where(Notification.read.is_(False))
    rows = session.scalars(statement.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)).all()
    return {"items": [_out(session, row, user_id) for row in rows], "unread": _unread_count(session, user_id)}


def unread(session: Session, user_id: int) -> dict:
    limit = get_int("notifications", "bell.limit", user_id=user_id)
    rows = session.scalars(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.show_browser.is_(True),
            Notification.read.is_(False),
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    ).all()
    return {"count": _unread_count(session, user_id), "items": [_out(session, row, user_id) for row in rows]}


def mark_read(session: Session, user_id: int, notification_id: int) -> dict:
    return _retry_write(session, lambda: _mark_read(session, user_id, notification_id))


def _mark_read(session: Session, user_id: int, notification_id: int) -> dict:
    row = _own(session, user_id, notification_id)
    row.read = True
    session.flush()
    publish_event("notifications.changed", user_id=user_id)
    with log_scope("notifications", "read", user_id=user_id):
        logger.info("notification read id={}", notification_id)
    return _out(session, row, user_id)


def mark_all_read(session: Session, user_id: int) -> dict:
    return _retry_write(session, lambda: _mark_all_read(session, user_id))


def _mark_all_read(session: Session, user_id: int) -> dict:
    rows = session.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.show_browser.is_(True),
            Notification.read.is_(False),
        )
    ).all()
    for row in rows:
        row.read = True
    session.flush()
    publish_event("notifications.changed", user_id=user_id)
    with log_scope("notifications", "read", user_id=user_id):
        logger.info("notifications read all count={}", len(rows))
    return {"updated": len(rows)}


def _retry_write(session: Session, action):
    last = None
    for attempt in range(3):
        try:
            result = action()
            session.commit()
            return result
        except OperationalError as exc:
            last = exc
            session.rollback()
            time.sleep(0.3 * (attempt + 1))
    raise HTTPException(status_code=503, detail="База занята записью почты, повторите") from last


def probe(user_id: int, channel: str) -> dict:
    if channel == "telegram":
        status, error = channels.send_telegram(user_id, "Проверка: бот доставляет сообщения из рабочего пространства.")
    elif channel == "email":
        status, error = channels.send_email(
            user_id,
            "Проверка почты",
            "Проверка: письмо из рабочего пространства дошло.",
        )
    else:
        raise HTTPException(status_code=400, detail="Неизвестный канал")
    if status != "sent":
        raise HTTPException(status_code=400, detail=error or "Не отправилось")
    with log_scope("notifications", "probe", user_id=user_id):
        logger.info("probe sent channel={}", channel)
    return {"ok": True}


def meta(user_id: int) -> dict:
    return {
        "events": _choices("events"),
        "channels": _choices("channels"),
        "statuses": _choices("statuses"),
        "matrix": _matrix(user_id),
    }


def _finish(delivery_id: int, status: str, error: str, channel: str) -> None:
    with session_scope() as session:
        row = session.get(NotificationDelivery, delivery_id)
        if row is None:
            return
        row.attempts = (row.attempts or 0) + 1
        row.updated_at = utcnow()
        row.last_error = _clip_error(error)
        if status == "sent":
            row.status = "sent"
            row.sent_at = utcnow()
            row.last_error = ""
            logger.info("delivery sent id={} channel={}", row.id, channel)
            return
        if status == "skipped":
            row.status = "skipped"
            logger.info("delivery skipped id={} channel={}", row.id, channel)
            return
        limit = get_int("notifications", "delivery.max_attempts")
        if row.attempts >= limit:
            row.status = "failed"
            logger.warning("delivery failed id={} channel={} attempts={}", row.id, channel, row.attempts)
            return
        row.status = "failed"
        base = get_int("notifications", "delivery.backoff_base_seconds")
        cap = get_int("notifications", "delivery.backoff_cap_seconds")
        delay = min(cap, base * (2 ** (row.attempts - 1)))
        row.next_attempt_at = utcnow() + timedelta(seconds=delay)
        logger.warning("delivery retry id={} channel={} attempts={} delay={}", row.id, channel, row.attempts, delay)


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


def _recipients(session: Session, message: EventMessage) -> list[User]:
    mode = get_str("notifications", "audience")
    if mode == "actor":
        ids: list[int] = []
        if message.user_id:
            ids.append(message.user_id)
        assignee = (message.payload or {}).get("assignee_id")
        if isinstance(assignee, int) and assignee not in ids:
            ids.append(assignee)
        if ids:
            return list(session.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))).all())
    return list(session.scalars(select(User).where(User.is_active.is_(True))).all())


def _flags(user_id: int, event_type: str) -> dict[str, bool]:
    matrix = _matrix(user_id)
    flags = matrix.get(event_type)
    if not isinstance(flags, dict):
        flags = {}
    return {item["id"]: bool(flags.get(item["id"])) for item in _choices("channels")}


def _matrix(user_id: int | None) -> dict:
    raw = get("notifications", "matrix", user_id=user_id)
    fallback = get("notifications", "matrix.fallback", user_id=user_id)
    if not isinstance(fallback, dict):
        fallback = {}
    result = {}
    channel_ids = [item["id"] for item in _choices("channels")]
    for event in _choices("events"):
        source = raw.get(event["id"]) if isinstance(raw, dict) else None
        if not isinstance(source, dict):
            source = fallback
        result[event["id"]] = {channel: bool(source.get(channel)) for channel in channel_ids}
    return result


def _dedup_exists(session: Session, user_id: int, dedup: str) -> bool:
    found = session.scalars(
        select(Notification.id).where(Notification.user_id == user_id, Notification.dedup_key == dedup)
    ).first()
    return found is not None


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


def _unread_count(session: Session, user_id: int) -> int:
    value = session.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id,
            Notification.show_browser.is_(True),
            Notification.read.is_(False),
        )
    )
    return int(value or 0)


def _own(session: Session, user_id: int, notification_id: int) -> Notification:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user_id or not row.show_browser:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    return row


def _choices(key: str) -> list[dict]:
    raw = get("notifications", key)
    items = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and str(item.get("id") or "").strip():
                code = str(item["id"]).strip()
                if code in seen:
                    continue
                seen.add(code)
                items.append({"id": code, "label": str(item.get("label") or code)})
    if key == "events":
        from app.modules.notifications.settings import _EVENTS

        for item in _EVENTS:
            code = item["id"]
            if code not in seen:
                items.append({"id": code, "label": item["label"]})
    return items


def _label(key: str, code: str) -> str:
    for item in _choices(key):
        if item["id"] == code:
            return item["label"]
    return code


def _clip(value: str, key: str) -> str:
    text = value or ""
    limit = get_int("notifications", key)
    if len(text) <= limit:
        return text
    return text[:limit]


def _clip_error(value: str) -> str:
    return _clip(" ".join((value or "").split()), "error.max_chars")


def known_events() -> tuple[str, ...]:
    return ALL_EVENTS
