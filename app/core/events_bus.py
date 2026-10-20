"""Шина событий в процессе: сигналы для открытых SSE-каналов.

Пишут сюда планировщик (забор почты) и обработчики запросов (прочитано,
архив, уведомления). Читает только SSE-генератор из app/core/sse.py —
по одной очереди на открытое соединение.

Требования:
- publish никогда не блокирует вызывающего (джоба или запрос важнее вкладки);
- переполненная очередь тихо выбрасывает событие: счётчики пересчитываются
  по heartbeat, потеря сигнала не портит состояние;
- user_id=None означает «всем соединениям», иначе — только этому пользователю.
"""

from __future__ import annotations

import queue
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

QUEUE_LIMIT = 200

@dataclass
class BusEvent:
    type: str
    payload: dict = field(default_factory=dict)
    user_id: int | None = None


_subscribers: list[tuple[int | None, queue.Queue]] = []
_lock = threading.Lock()
_dropped = 0


def publish(event_type: str, payload: dict | None = None, user_id: int | None = None) -> None:
    """Раздать событие подписчикам. Вызов безопасен из любого потока."""
    global _dropped
    event = BusEvent(type=event_type, payload=dict(payload or {}), user_id=user_id)
    with _lock:
        subscribers = list(_subscribers)
    for subscriber_user_id, q in subscribers:
        if event.user_id is not None and subscriber_user_id != event.user_id:
            continue
        try:
            q.put_nowait(event)
        except queue.Full:
            with _lock:
                _dropped += 1


@contextmanager
def subscribe(user_id: int | None):
    """Очередь событий для одного соединения. Выход — отписка."""
    q: queue.Queue = queue.Queue(maxsize=QUEUE_LIMIT)
    with _lock:
        _subscribers.append((user_id, q))
    try:
        yield q
    finally:
        with _lock:
            try:
                _subscribers.remove((user_id, q))
            except ValueError:
                pass


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)


def dropped() -> int:
    with _lock:
        return _dropped
