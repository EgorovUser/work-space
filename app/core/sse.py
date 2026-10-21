"""SSE-канал /api/events: живые счётчики для открытой вкладки.

Формат потока (text/event-stream):

- ``event: state`` — снимок счётчиков (непрочитанные письма и уведомления,
  корзина, секреты — патч T); первый уходит сразу при подключении, дальше —
  когда пришёл сигнал из шины или на heartbeat (он же keepalive и проверка
  сессии);
- ``event: mail.sync`` — забор почты реально принёс письма (ящик + количество);
- ``event: mail.changed`` — какое-то письмо изменилось (прочитано, архив,
  удаление, импорт) — в том числе из другой вкладки;
- ``event: notifications.new`` — новое уведомление целиком: заголовок, текст,
  ссылка и флаг os (патч AO). Фронт показывает по нему системный тост
  операционной системы, если пользователь включил канал «Системные
  уведомления» и дал разрешение браузеру;
- ``: ping`` — heartbeat без изменений, чтобы прокси не рвали соединение.

Сигналы из шины не несут счётчиков сами: генератор пересчитывает их в своём
потоке после короткой паузы (запросы успевают доехать до коммита). Пропущенный
сигнал не страшен — heartbeat пересчитает состояние ещё раз.

Сами числа живут в хабе ``app/core/counters.py`` (патч T): после сигнала шины
здесь принудительный пересчёт (мимо кеша), на heartbeat — чтение из кеша с
TTL — сколько бы вкладок ни висело открытыми, к базе ходит один запрос на
окно, а мутации сбрасывают кеш сами.
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
            state = await run_in_threadpool(_snapshot, user_id, True)
            last_state = dict(state)
            yield _format("state", state)
            while True:
                if await request.is_disconnected():
                    break
                first = await _wait_event(q, heartbeat)
                if first is None:
                    if not await run_in_threadpool(_session_alive, request):
                        break
                    # Heartbeat — чтение из кеша счётчиков: мутации кеш сбрасывают,
                    # поэтому число не зависает, а лишних запросов к базе нет.
                    state = await run_in_threadpool(_snapshot, user_id, False)
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
                    elif item.type == "notifications.new":
                        # Само уведомление для системного тоста (патч AO):
                        # показывает только вкладка-лидер с включённым
                        # каналом и разрешением браузера.
                        yield _format("notifications.new", item.payload)
                await asyncio.sleep(_DEBOUNCE_SECONDS)
                # Сигнал был — пересчитываем мимо кеша и обновляем его.
                state = await run_in_threadpool(_snapshot, user_id, True)
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


def _snapshot(user_id: int, force: bool = False) -> dict:
    """Счётчики из хаба (патч T). Упавший модуль не роняет канал — поля просто нет."""
    from app.core import counters

    return counters.user_state(user_id, force=force)


def _session_alive(request: Request) -> bool:
    """Сессия могла протухнуть, пока вкладка держит канал открытый."""
    user_id = request.session.get("user_id")
    version = request.session.get("session_version")
    if not user_id or version is None:
        return False
    with db_module.SessionLocal() as session:
        user = session.get(User, user_id)
    return user is not None and bool(user.is_active) and version == user.session_version
