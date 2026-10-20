"""Валидация входов документов: название и текстовые поля с лимитами."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.core.settings_store import get_int


def _clean_title(title: str, fallback_name: str) -> str:
    text = (title or "").strip()
    if not text:
        text = Path(fallback_name or "").stem.strip() or (fallback_name or "").strip()
    limit = get_int("documents", "title.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Укажите название")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Название длиннее " + str(limit) + " символов")
    return text


def _clean_note(note: str | None, key: str) -> str:
    text = note or ""
    limit = get_int("documents", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Текст длиннее " + str(limit) + " символов")
    return text
