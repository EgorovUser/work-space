"""Валидация входов документов: название и текстовые поля с лимитами."""

from __future__ import annotations

from app.core.text import clean_limited, clean_name, file_stem


def _clean_title(title: str, fallback_name: str) -> str:
    fallback = file_stem(fallback_name) or (fallback_name or "").strip()
    return clean_name("documents", "title.max_length", title, fallback=fallback)


def _clean_note(note: str | None, key: str) -> str:
    return clean_limited("documents", key, note, strip=False)
