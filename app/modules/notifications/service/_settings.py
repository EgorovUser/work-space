"""Настройки уведомлений: каталоги событий/каналов/статусов, матрица, лимиты."""

from __future__ import annotations

from app.core.settings_store import get, get_int


def _choices(key: str) -> list[dict]:
    raw = get("notifications", key)
    items = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and str(item.get("id") or "").strip():
                code = str(item["id"]).strip()
                if code in seen:
                    continue
                seen.add(code)
                items.append({"id": code, "label": str(item.get("label") or code)})
    if key == "events":
        from app.modules.notifications.settings import _EVENTS

        for item in _EVENTS:
            code = item["id"]
            if code not in seen:
                items.append({"id": code, "label": item["label"]})
    return items


def _label(key: str, code: str) -> str:
    for item in _choices(key):
        if item["id"] == code:
            return item["label"]
    return code


def _clip(value: str, key: str) -> str:
    text = value or ""
    limit = get_int("notifications", key)
    if len(text) <= limit:
        return text
    return text[:limit]


def _clip_error(value: str) -> str:
    return _clip(" ".join((value or "").split()), "error.max_chars")


def _matrix(user_id: int | None) -> dict:
    raw = get("notifications", "matrix", user_id=user_id)
    fallback = get("notifications", "matrix.fallback", user_id=user_id)
    if not isinstance(fallback, dict):
        fallback = {}
    result = {}
    channel_ids = [item["id"] for item in _choices("channels")]
    for event in _choices("events"):
        source = raw.get(event["id"]) if isinstance(raw, dict) else None
        if not isinstance(source, dict):
            source = fallback
        result[event["id"]] = {channel: bool(source.get(channel)) for channel in channel_ids}
    return result


def _flags(user_id: int, event_type: str) -> dict[str, bool]:
    matrix = _matrix(user_id)
    flags = matrix.get(event_type)
    if not isinstance(flags, dict):
        flags = {}
    return {item["id"]: bool(flags.get(item["id"])) for item in _choices("channels")}
