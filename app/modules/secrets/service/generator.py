"""Генератор секретов: алфавит из настроек, случайная строка нужной длины."""

from __future__ import annotations

from secrets import choice as random_choice

from fastapi import HTTPException

from app.core.logging import log_scope, logger
from app.core.settings_store import get_bool, get_int, get_str


def generate_secret(project_id: int) -> dict:
    length = get_int("secrets", "generator.length", project_id=project_id)
    alphabet = _alphabet(project_id)
    if not alphabet:
        raise HTTPException(status_code=400, detail="Алфавит генератора пуст")
    value = "".join(random_choice(alphabet) for _ in range(length))
    with log_scope("secrets", "generate"):
        logger.info("secret generated length={}", length)
    return {"secret": value}


def _alphabet(project_id: int) -> str:
    chunks = []
    if get_bool("secrets", "generator.lowercase", project_id=project_id):
        chunks.append(get_str("secrets", "generator.lowercase_chars"))
    if get_bool("secrets", "generator.uppercase", project_id=project_id):
        chunks.append(get_str("secrets", "generator.uppercase_chars"))
    if get_bool("secrets", "generator.digits", project_id=project_id):
        chunks.append(get_str("secrets", "generator.digits_chars"))
    if get_bool("secrets", "generator.symbols", project_id=project_id):
        chunks.append(get_str("secrets", "generator.symbols_chars"))
    excluded = set(get_str("secrets", "generator.exclude", project_id=project_id))
    seen: list[str] = []
    for char in "".join(chunks):
        if char in excluded or char in seen:
            continue
        seen.append(char)
    return "".join(seen)
