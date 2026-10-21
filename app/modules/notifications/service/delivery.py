"""Доставка уведомлений: событие аутбокса → уведомления, каналы, повторы."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import session_scope, utcnow
from app.core.logging import log_scope, logger
from app.core.models import User
from app.core.outbox import EventMessage
from app.core.settings_store import get_bool, get_int, get_str
from app.modules.notifications import channels
from app.modules.notifications.models import Notification, NotificationDelivery
from app.modules.notifications.service._bus import publish_event
from app.modules.notifications.service._queries import _dedup_exists
from app.modules.notifications.service._serialize import _compose, _outgoing
from app.modules.notifications.service._settings import _choices, _clip_error, _flags


def handle(message: EventMessage) -> None:
    delivery_ids: list[int] = []
    fresh: list[tuple[int, dict]] = []
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
                # browser живёт во вкладке (лента/бейдж), os — тост
                # операционной системы у клиента (патч AO): ни тому, ни
                # другому серверная очередь доставок не нужна.
                if channel in ("browser", "os") or not enabled:
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
            # Само уведомление — живым вкладкам пользователя (патч AO):
            # фронт решает по флагу os и местным тумблерам, показывать ли
            # системный тост. Адресно: матрица каналов у каждого своя.
            fresh.append(
                (
                    user.id,
                    {
                        "id": row.id,
                        "title": title,
                        "body": body,
                        "link": link,
                        "event_type": message.event_type,
                        "os": bool(flags.get("os")),
                    },
                )
            )
            created += 1
        if created:
            with log_scope("notifications", "create", user_id=message.user_id):
                logger.info("notifications created event={} count={}", message.event_type, created)
            # Открытые вкладки пересчитают свой счётчик уведомлений сразу.
            publish_event("notifications.changed")
            for fresh_user_id, payload in fresh:
                publish_event("notifications.new", payload, fresh_user_id)
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
                if channel in ("browser", "os") or not enabled or channel in existing:
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
