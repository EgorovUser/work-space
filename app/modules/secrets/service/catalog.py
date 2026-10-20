"""Каталог видов секретов: список {id, label} из настроек и подпись вида."""

from __future__ import annotations

from app.core.text import catalog_label, choices_catalog


def _kinds(project_id: int) -> list[dict]:
    return choices_catalog("secrets", "kinds", project_id=project_id)


def _kind_label(kind: str, project_id: int) -> str:
    return catalog_label(_kinds(project_id), kind)
