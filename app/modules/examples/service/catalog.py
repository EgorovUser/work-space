"""Каталог языков примеров: список {id, label} из настроек и подпись."""

from __future__ import annotations

from app.core.settings_store import get


def _languages(project_id: int) -> list[dict]:
    raw = get("examples", "languages", project_id=project_id)
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


def _language_label(language: str, project_id: int) -> str:
    for item in _languages(project_id):
        if item["id"] == language:
            return item["label"]
    return language or ""
