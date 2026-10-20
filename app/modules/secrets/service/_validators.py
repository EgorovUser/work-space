"""Валидация входов секретов: название, лимитированные поля, сам секрет, вид."""

from __future__ import annotations

from fastapi import HTTPException

from app.core.settings_store import get_bool, get_int
from app.modules.secrets.service.catalog import _kinds


def _clean_title(title: str) -> str:
    text = (title or "").strip()
    limit = get_int("secrets", "title.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Укажите название")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Название длиннее " + str(limit) + " символов")
    return text


def _clean_limit(value: str, key: str, strip: bool) -> str:
    text = value or ""
    if strip:
        text = text.strip()
    limit = get_int("secrets", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Текст длиннее " + str(limit) + " символов")
    return text


def _clean_secret(value: str, project_id: int, required: bool) -> str:
    text = value or ""
    limit = get_int("secrets", "secret.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Секрет длиннее " + str(limit) + " символов")
    must = required and get_bool("secrets", "secret.required", project_id=project_id)
    if must and not text:
        raise HTTPException(status_code=400, detail="Укажите секрет")
    if not required and not text and get_bool("secrets", "secret.required", project_id=project_id):
        raise HTTPException(status_code=400, detail="Секрет нельзя очистить")
    return text


def _clean_kind(value: str | None, project_id: int) -> str:
    from app.core.settings_store import get_str

    text = (value or "").strip()
    if not text:
        text = get_str("secrets", "kind.default", project_id=project_id).strip()
    limit = get_int("secrets", "kind.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Вид длиннее " + str(limit) + " символов")
    if not text:
        return ""
    known = {item["id"] for item in _kinds(project_id)}
    if known and text not in known and not get_bool("secrets", "kind.allow_custom", project_id=project_id):
        raise HTTPException(status_code=400, detail="Вид не из списка")
    return text


def _query_needle(query: str, project_id: int) -> str:
    text = (query or "").strip()
    minimum = get_int("secrets", "list.query.min_length", project_id=project_id)
    if text and len(text) < minimum:
        raise HTTPException(status_code=400, detail="Фильтр короче " + str(minimum) + " символов")
    return text.casefold()
