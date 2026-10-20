"""Каталог языков примеров: список {id, label} из настроек и подпись."""

from __future__ import annotations

from app.core.text import catalog_label, choices_catalog


def _languages(project_id: int) -> list[dict]:
    return choices_catalog("examples", "languages", project_id=project_id)


def _language_label(language: str, project_id: int) -> str:
    return catalog_label(_languages(project_id), language)
