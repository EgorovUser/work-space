"""Валидация входов примеров: название, текст, заметка, язык, метки, фильтр."""

from __future__ import annotations

from fastapi import HTTPException

from app.core.settings_store import get_bool, get_int, get_str
from app.modules.examples.service.catalog import _languages


def _clean_title(title: str) -> str:
    text = (title or "").strip()
    limit = get_int("examples", "title.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Укажите название")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Название длиннее " + str(limit) + " символов")
    return text


def _clean_body(body: str, project_id: int) -> str:
    text = body or ""
    limit = get_int("examples", "body.max_length", project_id=project_id)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Текст длиннее " + str(limit) + " символов")
    if get_bool("examples", "body.required", project_id=project_id) and not text.strip():
        raise HTTPException(status_code=400, detail="Укажите текст примера")
    return text


def _clean_note(note: str) -> str:
    text = note or ""
    limit = get_int("examples", "note.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Заметка длиннее " + str(limit) + " символов")
    return text


def _clean_language(value: str | None, project_id: int) -> str:
    text = (value or "").strip()
    if not text:
        text = get_str("examples", "language.default", project_id=project_id).strip()
    limit = get_int("examples", "language.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Язык длиннее " + str(limit) + " символов")
    if not text:
        return ""
    known = {item["id"] for item in _languages(project_id)}
    allow_custom = get_bool("examples", "language.allow_custom", project_id=project_id)
    if known and text not in known and not allow_custom:
        raise HTTPException(status_code=400, detail="Язык не из списка")
    return text


def _clean_tag_names(names: list[str], project_id: int) -> list[str]:
    separator = get_str("examples", "tag.separator")
    limit = get_int("examples", "tag.name.max_length")
    maximum = get_int("examples", "tag.max_count", project_id=project_id)
    pieces: list[str] = []
    for name in names:
        raw = name or ""
        chunks = raw.split(separator) if separator else [raw]
        pieces.extend(chunks)
    result: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        text = piece.strip()
        if not text:
            continue
        if len(text) > limit:
            raise HTTPException(status_code=400, detail="Метка длиннее " + str(limit) + " символов")
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    if len(result) > maximum:
        raise HTTPException(status_code=400, detail="Меток больше " + str(maximum))
    return result


def _query_needle(query: str, project_id: int) -> str:
    text = (query or "").strip()
    minimum = get_int("examples", "list.query.min_length", project_id=project_id)
    if text and len(text) < minimum:
        raise HTTPException(status_code=400, detail="Фильтр короче " + str(minimum) + " символов")
    return text.casefold()
