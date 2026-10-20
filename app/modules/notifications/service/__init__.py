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

__all__ = [
    "ALL_EVENTS",
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
