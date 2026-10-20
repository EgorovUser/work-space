"""Версии документа: сохранение загрузки, новая версия, удаление версии.

Сюда же — связка файла с проектом и событие «документ загружен»: это
общее для создания документа, создания из вложения письма и новой версии.
"""

from __future__ import annotations

import mimetypes

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_catalog import DOC_UPLOADED, DOC_VERSION, DOC_VERSION_DELETED
from app.core.files import _read_limited, add_link, save_bytes
from app.core.logging import log_scope, logger
from app.core.models import StoredFile
from app.core.outbox import enqueue
from app.core.settings_store import get_int
from app.modules.documents.extract import ERROR, extract_bytes
from app.modules.documents.models import Document, DocumentVersion
from app.modules.documents.service._queries import _document, _drop_links, _ensure_room, _next_number, _versions
from app.modules.documents.service._serialize import _full
from app.modules.documents.service._validators import _clean_note
from app.modules.projects.service import touch_project


def add_version(
    session: Session,
    project_id: int,
    user_id: int,
    document_id: int,
    upload: UploadFile,
    version_note: str,
) -> dict:
    document = _document(session, project_id, document_id)
    _ensure_room(session, document)
    stored, parsed = _store_upload(session, project_id, user_id, upload)
    version = _add_version(
        session,
        document,
        stored,
        parsed,
        user_id,
        _clean_note(version_note, "version.note.max_length"),
    )
    document.updated_at = utcnow()
    _link_and_event(session, project_id, user_id, document, version)
    touch_project(session, project_id)
    with log_scope("documents", "version", user_id=user_id):
        logger.info(
            "document version id={} number={} file={} status={}",
            document.id,
            version.version_number,
            stored.id,
            version.extract_status,
        )
    enqueue(
        session,
        DOC_VERSION,
        {
            "title": document.title,
            "project_id": project_id,
            "document_id": document.id,
            "link": "/projects/" + str(project_id) + "/documents/" + str(document.id),
        },
        user_id=user_id,
    )
    return _full(session, document)


def delete_version(session: Session, project_id: int, user_id: int, document_id: int, version_id: int) -> None:
    document = _document(session, project_id, document_id)
    versions = _versions(session, document.id)
    if len(versions) <= 1:
        raise HTTPException(status_code=400, detail="Это единственная версия — удалите документ")
    row = next((item for item in versions if item.id == version_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Версия не найдена")
    _drop_links(session, [row.id])
    session.delete(row)
    document.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        DOC_VERSION_DELETED,
        {
            "title": document.title,
            "project_id": project_id,
            "document_id": document.id,
            "link": "/projects/" + str(project_id) + "/documents/" + str(document.id),
        },
        user_id=user_id,
    )
    with log_scope("documents", "version.delete", user_id=user_id):
        logger.info("document version deleted id={} version={}", document.id, version_id)


def _store_upload(session: Session, project_id: int, user_id: int, upload: UploadFile):
    data = _read_limited(upload.file, get_int("core", "files.max_upload_mb") * 1024 * 1024)
    filename = upload.filename or "file"
    mime = upload.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    stored = save_bytes(session, data, filename, mime, user_id)
    parsed = extract_bytes(stored.original_name, data, project_id)
    attempts = 1 if parsed[1] == ERROR else 0
    return stored, (parsed[0], parsed[1], parsed[2], attempts)


def _add_version(session, document: Document, stored: StoredFile, parsed, user_id: int, note: str) -> DocumentVersion:
    _ensure_room(session, document)
    text, status, error, attempts = parsed
    number = _next_number(session, document.id)
    row = DocumentVersion(
        document_id=document.id,
        version_number=number,
        file_id=stored.id,
        original_name=stored.original_name,
        mime_type=stored.mime_type,
        size=stored.size,
        extracted_text=text,
        extract_status=status,
        extract_error=error,
        extract_attempts=attempts,
        note=note,
        created_by=user_id,
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def _link_and_event(session, project_id: int, user_id: int, document: Document, version: DocumentVersion) -> None:
    add_link(
        session,
        version.file_id,
        project_id=project_id,
        module="documents",
        entity_type="document_version",
        entity_id=version.id,
    )
    enqueue(
        session,
        DOC_UPLOADED,
        {
            "project_id": project_id,
            "document_id": document.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "title": document.title,
            "file_id": version.file_id,
        },
        user_id=user_id,
    )
