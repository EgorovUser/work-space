"""SSE-канал /api/events: живые счётчики для открытой вкладки.

Формат потока (text/event-stream):

- ``event: state`` — снимок счётчиков ``mail_unread`` и ``notifications_unread``;
  первый уходит сразу при подключении, дальше — когда пришёл сигнал из шины
  или на heartbeat (он же keepalive и проверка сессии);
- ``event: mail.sync`` — забор почты реально принёс письма (ящик + количество);
- ``event: mail.changed`` — какое-то письмо изменилось (прочитано, архив,
  удаление, импорт) — в том числе из другой вкладки;
- ``: ping`` — heartbeat без изменений, чтобы прокси не рвали соединение.

Сигналы из шины не несут счётчиков сами: генератор пересчитывает их в своём
потоке после короткой паузы (запросы успевают доехать до коммита). Пропущенный
сигнал не страшен — heartbeat пересчитает состояние ещё раз.
"""

from __future__ import annotations

import asyncio
import json
import queue

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.core import db as db_module
from app.core import events_bus
from app.core.auth import require_user
from app.core.logging import log_scope, logger
from app.core.models import User
from app.core.settings_store import get_bool, get_int

router = APIRouter()

# Пауза после сигнала: дать транзакции запроса доехать до коммита,
# чтобы пересчитанные счётчики уже видели изменение.
_DEBOUNCE_SECONDS = 0.25


@router.get("/api/events")
async def events(request: Request, user: User = Depends(require_user)):
    if not get_bool("core", "events.enabled"):
        raise HTTPException(status_code=503, detail="Живые события выключены в настройках")
    heartbeat = max(5, get_int("core", "events.heartbeat_seconds"))
    with log_scope("core", "events.open", user_id=user.id):
        logger.info("sse open user_id={} subscribers={}", user.id, events_bus.subscriber_count())
    return StreamingResponse(
        _stream(request, user.id, heartbeat),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream(request: Request, user_id: int, heartbeat: int):
    last_state: dict | None = None
    with events_bus.subscribe(user_id) as q:
        try:
            state = await run_in_threadpool(_snapshot, user_id)
            last_state = dict(state)
            yield _format("state", state)
            while True:
                if await request.is_disconnected():
                    break
                first = await _wait_event(q, heartbeat)
                if first is None:
                    if not await run_in_threadpool(_session_alive, request):
                        break
                    state = await run_in_threadpool(_snapshot, user_id)
                    if state != last_state:
                        last_state = dict(state)
                        yield _format("state", state)
                    else:
                        yield ": ping\n\n"
                    continue
                # Сигнал пришёл: собираем всё накопившееся, чтобы один
                # пересчёт покрыл пачку (например, несколько ящиков сразу).
                items = [first]
                while True:
                    try:
                        items.append(q.get_nowait())
                    except queue.Empty:
                        break
                for item in items:
                    if item.type == "mail.sync":
                        yield _format("mail.sync", item.payload)
                    elif item.type == "mail.changed":
                        # Открытый список писем в другой вкладке должен увидеть,
                        # что письмо прочитано/удалено — без перезагрузки.
                        yield _format("mail.changed", item.payload)
                await asyncio.sleep(_DEBOUNCE_SECONDS)
                state = await run_in_threadpool(_snapshot, user_id)
                if state != last_state:
                    last_state = dict(state)
                    yield _format("state", state)
        except asyncio.CancelledError:  # вкладка закрылась посреди записи
            pass
        finally:
            with log_scope("core", "events.close", user_id=user_id):
                logger.info("sse close user_id={}", user_id)


async def _wait_event(q: "queue.Queue", timeout: float):
    """Ждём событие, не блокируя цикл: у обычной очереди нет асинхронного get."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            return q.get_nowait()
        except queue.Empty:
            pass
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None
        await asyncio.sleep(min(0.1, remaining))


def _format(event_type: str, payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {body}\n\n"


def _snapshot(user_id: int) -> dict:
    """Счётчики для вкладки. Упавший модуль не роняет канал — поля просто нет."""
    state: dict = {}
    try:
        from sqlalchemy import func, select

        from app.modules.mail.models import MailMessage

        with db_module.SessionLocal() as session:
            unread = session.scalar(
                select(func.count())
                .select_from(MailMessage)
                .where(MailMessage.read.is_(False), MailMessage.archived.is_(False))
            )
        state["mail_unread"] = int(unread or 0)
    except Exception:
        logger.opt(exception=True).warning("sse mail snapshot failed")
    try:
        from sqlalchemy import func, select

        from app.modules.notifications.models import Notification

        with db_module.SessionLocal() as session:
            unread = session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.show_browser.is_(True),
                    Notification.read.is_(False),
                )
            )
        state["notifications_unread"] = int(unread or 0)
    except Exception:
        logger.opt(exception=True).warning("sse notifications snapshot failed")
    return state


def _session_alive(request: Request) -> bool:
    """Сессия могла протухнуть, пока вкладка держит канал открытый."""
    user_id = request.session.get("user_id")
    version = request.session.get("session_version")
    if not user_id or version is None:
        return False
    with db_module.SessionLocal() as session:
        user = session.get(User, user_id)
    return user is not None and bool(user.is_active) and version == user.session_version
