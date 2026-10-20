"""Документы: список, создание (загрузка и из вложения письма), правка,
мягкое удаление в корзину, восстановление, окончательная чистка, текст."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.versioning import check_version
from app.core.events_catalog import DOC_ARCHIVED, DOC_DELETED, DOC_UPDATED
from app.core.files import path_for
from app.core.logging import log_scope, logger
from app.core.models import StoredFile
from app.core.outbox import enqueue
from app.core.settings_store import get_int
from app.modules.documents.extract import ERROR, extract_bytes
from app.modules.documents.models import Document
from app.modules.documents.service._queries import _document, _drop_links, _versions
from app.modules.documents.service._serialize import _brief, _full
from app.modules.documents.service._validators import _clean_note, _clean_title
from app.modules.documents.service.versions import _add_version, _link_and_event, _store_upload
from app.modules.projects.service import touch_project


def list_documents(session: Session, project_id: int, include_archived: bool) -> dict:
    limit = get_int("documents", "list.limit", project_id=project_id)
    query = select(Document).where(
        Document.project_id == project_id,
        # Документы из корзины в списке не показываем (патч N).
        Document.deleted_at.is_(None),
    )
    if not include_archived:
        query = query.where(Document.archived.is_(False))
    rows = session.scalars(query.order_by(Document.updated_at.desc(), Document.id.desc()).limit(limit)).all()
    return {"items": [_brief(session, row) for row in rows]}


def create_document(
    session: Session,
    project_id: int,
    user_id: int,
    upload,
    title: str,
    note: str,
    version_note: str = "",
) -> dict:
    stored, parsed = _store_upload(session, project_id, user_id, upload)
    name = _clean_title(title, stored.original_name)
    text_note = _clean_note(note, "note.max_length")
    version_text = _clean_note(version_note, "version.note.max_length")
    now = utcnow()
    document = Document(
        project_id=project_id,
        title=name,
        note=text_note,
        archived=False,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.flush()
    version = _add_version(session, document, stored, parsed, user_id, version_text)
    _link_and_event(session, project_id, user_id, document, version)
    touch_project(session, project_id)
    with log_scope("documents", "create", user_id=user_id):
        logger.info(
            "document created id={} version={} file={} status={}",
            document.id,
            version.version_number,
            stored.id,
            version.extract_status,
        )
    return _full(session, document)


def get_document(session: Session, project_id: int, document_id: int) -> dict:
    return _full(session, _document(session, project_id, document_id))


def create_from_stored(
    session: Session,
    project_id: int,
    user_id: int | None,
    stored: StoredFile,
    title: str = "",
    note: str = "",
) -> dict:
    """Документ из уже сохранённого файла (патч N): без повторной загрузки.

    Так вложение письма попадает в «Документы» одним кликом: файл уже
    лежит в хранилище (files), здесь появляется запись документа с версией,
    извлечённым текстом и событием. Байты читаются с диска по sha256.
    """
    data = path_for(stored.sha256).read_bytes()
    parsed = extract_bytes(stored.original_name, data, project_id)
    attempts = 1 if parsed[1] == ERROR else 0
    name = _clean_title(title, stored.original_name)
    text_note = _clean_note(note, "note.max_length")
    now = utcnow()
    document = Document(
        project_id=project_id,
        title=name,
        note=text_note,
        archived=False,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.flush()
    version = _add_version(session, document, stored, (parsed[0], parsed[1], parsed[2], attempts), user_id, "")
    _link_and_event(session, project_id, user_id, document, version)
    touch_project(session, project_id)
    with log_scope("documents", "create.stored", user_id=user_id):
        logger.info(
            "document created from stored file id={} version={} file={} status={}",
            document.id,
            version.version_number,
            stored.id,
            version.extract_status,
        )
    return _full(session, document)


def update_document(session: Session, project_id: int, user_id: int, document_id: int, fields: dict) -> dict:
    document = _document(session, project_id, document_id)
    check_version(fields, document.updated_at, "Документ")
    changed = False
    archived = None
    if "title" in fields and fields["title"] is not None:
        title = _clean_title(fields["title"], "")
        if title != document.title:
            document.title = title
            changed = True
    if "note" in fields and fields["note"] is not None:
        note = _clean_note(fields["note"], "note.max_length")
        if note != document.note:
            document.note = note
            changed = True
    if "archived" in fields and fields["archived"] is not None:
        flag = bool(fields["archived"])
        if flag != document.archived:
            document.archived = flag
            archived = flag
    document.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    link = "/projects/" + str(project_id) + "/documents/" + str(document.id)
    if archived is True:
        enqueue(session, DOC_ARCHIVED, {"title": document.title, "project_id": project_id, "document_id": document.id, "link": link}, user_id=user_id)
    elif changed or archived is False:
        enqueue(session, DOC_UPDATED, {"title": document.title, "project_id": project_id, "document_id": document.id, "link": link}, user_id=user_id)
    with log_scope("documents", "update", user_id=user_id):
        logger.info("document updated id={} archived={}", document.id, document.archived)
    return _full(session, document)


def delete_document(session: Session, project_id: int, user_id: int, document_id: int) -> dict:
    """Мягкое удаление: документ уходит в корзину, версии остаются (патч N)."""
    document = _document(session, project_id, document_id)
    document.deleted_at = utcnow()
    document.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    with log_scope("documents", "delete", user_id=user_id):
        logger.info("document deleted id={}", document_id)
    enqueue(
        session,
        DOC_DELETED,
        {"title": "Документ удалён", "subject": document.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/documents"},
        user_id=user_id,
    )
    return {"id": document.id, "title": document.title, "deleted_at": document.deleted_at.isoformat()}


def restore_document(session: Session, project_id: int, user_id: int, document_id: int) -> dict:
    document = _document(session, project_id, document_id, in_trash=True)
    document.deleted_at = None
    document.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        DOC_UPDATED,
        {"title": "Документ восстановлен", "subject": document.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/documents/" + str(document.id)},
        user_id=user_id,
    )
    with log_scope("documents", "restore", user_id=user_id):
        logger.info("document restored id={}", document_id)
    return _full(session, document)


def purge_document(session: Session, project_id: int, user_id: int, document_id: int) -> None:
    """Окончательное удаление — только из корзины."""
    document = _document(session, project_id, document_id, in_trash=True)
    ids = [row.id for row in _versions(session, document.id)]
    _drop_links(session, ids)
    session.delete(document)
    touch_project(session, project_id)
    session.flush()
    with log_scope("documents", "purge", user_id=user_id):
        logger.info("document purged id={}", document_id)


def document_text(session: Session, project_id: int, document_id: int) -> dict:
    from app.modules.documents.service._queries import _current

    document = _document(session, project_id, document_id)
    current = _current(session, document.id)
    text = current.extracted_text if current is not None else ""
    return {"text": text, "extract_status": current.extract_status if current else "", "chars": len(text)}


def dashboard_provider(session: Session, project_id: int, user_id: int | None, limits: dict) -> dict:
    limit = int(limits.get("recent_documents") or 1)
    rows = session.scalars(
        select(Document)
        .where(Document.project_id == project_id, Document.archived.is_(False), Document.deleted_at.is_(None))
        .order_by(Document.updated_at.desc(), Document.id.desc())
        .limit(limit)
    ).all()
    return {
        "recent_documents": [
            {"id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat()} for row in rows
        ]
    }
