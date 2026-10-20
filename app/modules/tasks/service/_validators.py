"""Валидация входных значений модуля задач.

Чистка строк, лимиты длины, приоритеты, режимы прогресса, разбор дедлайнов
и часовые пояса. Все функции бросают HTTPException 400 при некорректном
входе — как и в остальном приложении.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.models import User
from app.core.settings_store import get, get_int, get_str
from app.modules.tasks.models import ChecklistItem, Task

REPEAT_KINDS = ("", "daily", "weekly", "monthly", "yearly")


def _assignee(session: Session, user_id: int | None) -> int | None:
    if user_id is None:
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    return user.id


def _priority(value: str | None, project_id: int) -> str:
    chosen = (value or "").strip() or get_str("tasks", "priority.default", project_id=project_id)
    allowed = _priority_ids()
    if chosen not in allowed:
        raise HTTPException(status_code=400, detail="Неизвестный приоритет")
    return chosen


def _priority_ids() -> set[str]:
    raw = get("tasks", "priorities")
    if not isinstance(raw, list):
        return set()
    return {str(item.get("id")) for item in raw if isinstance(item, dict) and item.get("id")}


def _progress_mode(value: str | None, project_id: int) -> str:
    chosen = (value or "").strip() or get_str("tasks", "progress.default", project_id=project_id)
    if chosen not in ("auto", "manual"):
        raise HTTPException(status_code=400, detail="Неизвестный режим прогресса")
    return chosen


def _manual(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=400, detail="Прогресс должен быть целым числом")
    limit = get_int("tasks", "progress.max")
    if value < 0 or value > limit:
        raise HTTPException(status_code=400, detail="Прогресс вне диапазона 0.." + str(limit))
    return value


def _progress(task: Task, checks: list[ChecklistItem]) -> int:
    limit = get_int("tasks", "progress.max")
    if task.progress_mode == "manual":
        return max(0, min(limit, int(task.progress_manual)))
    if not checks:
        return 0
    done = sum(1 for item in checks if item.done)
    return int(done * limit / len(checks))


def _deadline(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Не разобрали дату") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_zone())
    return parsed.astimezone(timezone.utc)


def _zone():
    name = get_str("core", "ui.timezone")
    if not name:
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except Exception:
        return datetime.now().astimezone().tzinfo


def _repeat_kind(value) -> str:
    chosen = str(value or "").strip()
    if chosen not in REPEAT_KINDS:
        raise HTTPException(status_code=400, detail="Неизвестный тип повтора")
    return chosen


def _repeat_interval(value) -> int:
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=400, detail="Интервал повтора — целое число")
    limit = get_int("tasks", "repeat.interval.max")
    if value < 1 or value > limit:
        raise HTTPException(status_code=400, detail="Интервал повтора вне диапазона 1.." + str(limit))
    return value


def _repeat_until(value) -> datetime | None:
    if value is None:
        return None
    return _deadline(value)


def _clean(value: str, key: str, empty: str) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=empty)
    limit = get_int("tasks", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Длиннее " + str(limit) + " символов")
    return text


def _text(value: str, key: str) -> str:
    text = value or ""
    limit = get_int("tasks", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Длиннее " + str(limit) + " символов")
    return text


def _color(value: str) -> str:
    text = (value or "").strip()
    if not text:
        text = get_str("tasks", "status.color.default")
    limit = get_int("tasks", "status.color.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Цвет длиннее " + str(limit) + " символов")
    return text
