from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.context import request_id_var
from app.core.db import session_scope, utcnow
from app.core.events_catalog import ALL_EVENTS, DONE, FAILED, PENDING, PROCESSING
from app.core.logging import log_scope, logger
from app.core.models import OutboxEvent

_handlers: dict[str, list] = {}
_handlers_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_next_at = 0.0


@dataclass
class EventMessage:
    id: int
    event_type: str
    payload: dict
    attempts: int
    request_id: str | None
    user_id: int | None


def subscribe(event_type: str, handler) -> None:
    with _handlers_lock:
        _handlers.setdefault(event_type, []).append(handler)


def enqueue(session, event_type: str, payload: dict | None, user_id: int | None = None) -> OutboxEvent:
    if event_type not in ALL_EVENTS:
        logger.warning("unknown event type={}", event_type)
    row = OutboxEvent(
        event_type=event_type,
        payload=payload or {},
        status=PENDING,
        attempts=0,
        next_attempt_at=utcnow(),
        created_at=utcnow(),
        request_id=request_id_var.get(),
        user_id=user_id,
        last_error=None,
    )
    session.add(row)
    session.flush()
    logger.info(
        "outbox enqueue type={} id={} keys={}",
        event_type,
        row.id,
        list((payload or {}).keys()),
    )
    return row


def recover_processing() -> None:
    with session_scope() as session:
        rows = session.scalars(select(OutboxEvent).where(OutboxEvent.status == PROCESSING)).all()
        for row in rows:
            row.status = PENDING
            row.next_attempt_at = utcnow()
        count = len(rows)
    if count:
        with log_scope("outbox", "recover"):
            logger.warning("outbox recovered stuck events count={}", count)


def dispatch_once() -> int:
    from app.core.settings_store import get_int

    batch = get_int("core", "outbox.batch_size")
    claimed: list[EventMessage] = []
    with session_scope() as session:
        rows = session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.status == PENDING)
            .where(OutboxEvent.next_attempt_at <= utcnow())
            .order_by(OutboxEvent.id)
            .limit(batch)
        ).all()
        for row in rows:
            row.status = PROCESSING
            claimed.append(
                EventMessage(
                    id=row.id,
                    event_type=row.event_type,
                    payload=dict(row.payload or {}),
                    attempts=row.attempts or 0,
                    request_id=row.request_id,
                    user_id=row.user_id,
                )
            )
    for message in claimed:
        _process(message)
    return len(claimed)


def stats() -> dict:
    with session_scope() as session:
        pending = session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.status.in_((PENDING, PROCESSING)))
        )
        failed = session.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == FAILED)
        )
    return {"pending": int(pending or 0), "failed": int(failed or 0)}


def running() -> bool:
    return _thread is not None and _thread.is_alive()


def poll_state() -> dict:
    every = _poll_seconds()
    left = _next_at - time.monotonic()
    return {
        "every_seconds": every,
        "next_in_seconds": 0 if left <= 0 else int(left),
        "running": running(),
    }


def setup() -> None:
    recover_processing()
    start()
    stats()


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="outbox", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=2)


def _loop() -> None:
    global _next_at
    while not _stop.is_set():
        try:
            dispatch_once()
        except Exception:
            with log_scope("outbox", "dispatch"):
                logger.exception("outbox loop error")
        pause = _poll_seconds()
        _next_at = time.monotonic() + pause
        _stop.wait(pause)


def _process(message: EventMessage) -> None:
    from datetime import timedelta

    from app.core.settings_store import get_int

    with _handlers_lock:
        handlers = list(_handlers.get(message.event_type, []))
    token = request_id_var.set(message.request_id or "-")
    errors: list[str] = []
    try:
        with log_scope("outbox", "dispatch", user_id=message.user_id):
            for handler in handlers:
                try:
                    handler(message)
                except Exception as exc:
                    logger.exception(
                        "outbox handler failed type={} id={} handler={}",
                        message.event_type,
                        message.id,
                        getattr(handler, "__name__", "handler"),
                    )
                    errors.append(getattr(handler, "__name__", "handler") + ": " + str(exc))
            with session_scope() as session:
                row = session.get(OutboxEvent, message.id)
                if row is None:
                    return
                if not errors:
                    row.status = DONE
                    row.last_error = None
                    logger.info(
                        "outbox done type={} id={} handlers={}",
                        message.event_type,
                        message.id,
                        len(handlers),
                    )
                    return
                row.attempts = (row.attempts or 0) + 1
                row.last_error = "\n".join(errors)[:2000]
                limit = get_int("core", "outbox.max_attempts")
                if row.attempts >= limit:
                    row.status = FAILED
                    logger.error(
                        "outbox failed type={} id={} attempts={}",
                        message.event_type,
                        message.id,
                        row.attempts,
                    )
                    return
                row.status = PENDING
                base = get_int("core", "outbox.backoff_base_seconds")
                cap = get_int("core", "outbox.backoff_cap_seconds")
                delay = min(cap, base * (2 ** (row.attempts - 1)))
                row.next_attempt_at = utcnow() + timedelta(seconds=delay)
                logger.warning(
                    "outbox retry type={} id={} attempts={} delay={}",
                    message.event_type,
                    message.id,
                    row.attempts,
                    delay,
                )
    finally:
        request_id_var.reset(token)


def _poll_seconds() -> int:
    try:
        from app.core.settings_store import get_int

        return max(1, get_int("core", "outbox.poll_seconds"))
    except Exception:
        return 5
