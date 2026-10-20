"""Общие текстовые хелперы модулей: названия, лимиты, фильтры, сниппеты, каталоги.

Шесть модулей держали свои копии этих функций с точностью до имени ключа
настройки. Теперь реализация одна, в параметрах — только то, что реально
отличается: модуль, ключ и тексты сообщений.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.core.settings_store import get, get_int


def clean_name(module: str, key: str, value: str, *, fallback: str = "") -> str:
    """Название: strip, при пустоте — fallback, дальше лимит из настроек.

    Сообщения едины для всех модулей: «Укажите название» и «Название
    длиннее N символов» — так и было в документах, секретах, примерах,
    RDP и проектах.
    """
    text = (value or "").strip()
    if not text and fallback:
        text = fallback.strip()
    limit = get_int(module, key)
    if not text:
        raise HTTPException(status_code=400, detail="Укажите название")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Название длиннее " + str(limit) + " символов")
    return text


def clean_limited(module: str, key: str, value: str | None, *, strip: bool = True, long_prefix: str = "Текст длиннее ") -> str:
    """Текстовое поле с лимитом: пустое проходит, длиннее — 400.

    ``long_prefix`` различается у модулей: «Текст», «Заметка», «Описание».
    """
    text = value or ""
    if strip:
        text = text.strip()
    limit = get_int(module, key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail=long_prefix + str(limit) + " символов")
    return text


def search_needle(module: str, key: str, value: str, project_id: int | None) -> str:
    """Фильтр списка: минимум длины из настроек, дальше casefold."""
    text = (value or "").strip()
    minimum = get_int(module, key, project_id=project_id)
    if text and len(text) < minimum:
        raise HTTPException(status_code=400, detail="Фильтр короче " + str(minimum) + " символов")
    return text.casefold()


def snippet(text: str, needle: str, limit: int) -> str:
    """Фрагмент вокруг первого вхождения (поиск документов и примеров)."""
    folded = text.casefold()
    position = folded.find(needle)
    if position < 0:
        chunk = text[:limit]
    else:
        start = max(0, position - limit // 3)
        chunk = text[start : start + limit]
        if start:
            chunk = "…" + chunk
    chunk = " ".join(chunk.split())
    if len(chunk) > limit:
        return chunk[:limit] + "…"
    return chunk


def choices_catalog(module: str, key: str, project_id: int | None = None, user_id: int | None = None) -> list[dict]:
    """Каталог {id, label} из настройки-списка: виды секретов, языки примеров.

    Элементы бывают словарями или строками; пустые id пропускаются.
    """
    raw = get(module, key, project_id=project_id, user_id=user_id)
    items: list[dict] = []
    if not isinstance(raw, list):
        return items
    for item in raw:
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            code = str(item["id"]).strip()
            label = str(item.get("label") or code).strip() or code
            items.append({"id": code, "label": label})
        elif isinstance(item, str) and item.strip():
            items.append({"id": item.strip(), "label": item.strip()})
    return items


def catalog_label(items: list[dict], code: str) -> str:
    """Подпись элемента каталога по коду; нет кода — сам код."""
    for item in items:
        if item["id"] == code:
            return item["label"]
    return code or ""


def file_stem(name: str) -> str:
    """Основа имени файла без расширения — fallback названия документа."""
    return Path(name or "").stem.strip()
