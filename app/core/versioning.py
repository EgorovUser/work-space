"""Оптимистичная блокировка записей.

PATCH со значением updated_at, не совпадающим с текущим, получает 409: так
две открытые вкладки не затирают правки друг друга молча. Клиент, который
не присылает updated_at (старый фронтенд, скрипты), работает как раньше.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def check_version(fields: dict, current: datetime, label: str) -> None:
    claimed_raw = fields.get("updated_at")
    if not claimed_raw:
        return
    try:
        claimed = _aware(datetime.fromisoformat(str(claimed_raw).replace("Z", "+00:00")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Не удалось разобрать дату изменения записи") from exc
    if claimed != _aware(current):
        raise HTTPException(
            status_code=409,
            detail=label + " изменён в другой вкладке или на другом устройстве. Обновите страницу.",
        )
