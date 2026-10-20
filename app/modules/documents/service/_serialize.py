"""Сериализация документов: краткая строка списка, полная карточка, версия."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.settings_store import get_int
from app.modules.documents.extract import status_label
from app.modules.documents.models import Document, DocumentVersion
from app.modules.documents.service._queries import _current, _versions


def _brief(session: Session, document: Document) -> dict:
    current = _current(session, document.id)
    count = session.scalar(
        select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == document.id)
    )
    return {
        "id": document.id,
        "project_id": document.project_id,
        "title": document.title,
        "note": document.note or "",
        "archived": bool(document.archived),
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
        "version_count": int(count or 0),
        "current": _version_out(current) if current is not None else None,
    }


def _full(session: Session, document: Document) -> dict:
    versions = _versions(session, document.id)
    preview_limit = get_int("documents", "preview.max_chars", project_id=document.project_id)
    current = versions[0] if versions else None
    text = current.extracted_text if current is not None else ""
    payload = _brief(session, document)
    payload["versions"] = [_version_out(row) for row in versions]
    payload["preview"] = text[:preview_limit]
    payload["preview_truncated"] = len(text) > preview_limit
    payload["version_count"] = len(versions)
    return payload


def _version_out(row: DocumentVersion) -> dict:
    return {
        "id": row.id,
        "version_number": row.version_number,
        "file_id": row.file_id,
        "original_name": row.original_name,
        "mime_type": row.mime_type,
        "size": row.size,
        "extract_status": row.extract_status,
        "extract_label": status_label(row.extract_status),
        "extract_error": row.extract_error or "",
        "note": row.note or "",
        "text_length": len(row.extracted_text or ""),
        "created_at": row.created_at.isoformat(),
    }
