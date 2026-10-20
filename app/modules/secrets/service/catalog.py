"""Каталог видов секретов: список {id, label} из настроек и подпись вида."""

from __future__ import annotations

from app.core.settings_store import get


def _kinds(project_id: int) -> list[dict]:
    raw = get("secrets", "kinds", project_id=project_id)
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


def _kind_label(kind: str, project_id: int) -> str:
    for item in _kinds(project_id):
        if item["id"] == kind:
            return item["label"]
    return kind or ""
