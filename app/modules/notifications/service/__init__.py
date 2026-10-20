"""Сервис уведомлений, разбитый на тематические файлы.

Публичный API реэкспортируется отсюда целиком, поэтому внешние импорты
(``from app.modules.notifications import service`` в router.py и подписка
outbox) не меняются.

Раскладка по файлам:

- ``_bus.py``      — сигнал шины + сброс кеша счётчиков одним местом;
- ``_settings.py`` — каталоги событий/каналов/статусов, матрица, лимиты;
- ``_queries.py``  — своё уведомление, непрочитанные, дедупликация;
- ``_serialize.py`` — dict-ответы и исходящие тексты;
- ``feed.py``      — лента: списки, отметки о прочтении, мета, пробы;
- ``delivery.py``  — событие аутбокса → уведомления, каналы, повторы.
"""

from app.core.events_catalog import ALL_EVENTS
from app.modules.notifications.service.delivery import deliver_due, handle, send_delivery
from app.modules.notifications.service.feed import (
    home_items,
    list_notifications,
    mark_all_read,
    mark_read,
    meta,
    probe,
    unread,
)
from app.modules.notifications.service._queries import _dedup_exists


def dedup_exists(session, user_id: int, dedup: str) -> bool:
    """Публичная проверка дедуп-ключа: чужим модулям нужно решить, стоит ли
    ставить событие в аутбокс, не зная внутренностей уведомлений (патч AM —
    джоба «час по таймеру» в timetracking)."""
    return _dedup_exists(session, user_id, dedup)


__all__ = [
    "ALL_EVENTS",
    "dedup_exists",
    "deliver_due",
    "handle",
    "home_items",
    "list_notifications",
    "mark_all_read",
    "mark_read",
    "meta",
    "probe",
    "send_delivery",
    "unread",
]


def known_events() -> tuple[str, ...]:
    return ALL_EVENTS
