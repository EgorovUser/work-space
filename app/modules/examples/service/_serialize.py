"""Сериализация примеров: краткая строка списка и полная карточка."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.settings_store import get_int, get_str
from app.modules.examples.models import Example
from app.modules.examples.service._queries import _file_counts, _files, _tags_for
from app.modules.examples.service.catalog import _language_label, _languages


def _brief(row: Example, tags: list[dict], file_count: int, project_id: int) -> dict:
    preview_limit = get_int("examples", "preview.max_chars", project_id=project_id)
    body = row.body or ""
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "note": row.note or "",
        "language": row.language or "",
        "language_label": _language_label(row.language, project_id),
        "pinned": bool(row.pinned),
        "archived": bool(row.archived),
        "preview": body[:preview_limit],
        "preview_truncated": len(body) > preview_limit,
        "tags": tags,
        "file_count": file_count,
        "files": [],
        "updated_at": row.updated_at.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def _full(session: Session, row: Example) -> dict:
    tags = _tags_for(session, [row.id]).get(row.id, [])
    counts = _file_counts(session, row.project_id, [row.id])
    payload = _brief(row, tags, counts.get(row.id, 0), row.project_id)
    payload["body"] = row.body or ""
    payload["files"] = _files(session, row.id)
    payload["languages"] = _languages(row.project_id)
    payload["tag_separator"] = get_str("examples", "tag.separator")
    return payload
