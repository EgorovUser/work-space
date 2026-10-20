"""Сигнал шины уведомлений + сброс кеша счётчиков одним местом."""

from __future__ import annotations

from app.core import counters
from app.core.events_bus import publish as _bus_publish


def publish_event(event_type, payload=None, user_id=None):
    """Сигнал шины + сброс кеша счётчиков (патч T): уведомления менялись — числа бейджей тоже."""
    _bus_publish(event_type, payload, user_id)
    counters.invalidate()
