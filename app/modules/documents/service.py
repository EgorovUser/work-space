from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import session_scope, utcnow
from app.core.versioning import check_version
from app.core.events_catalog import DOC_ARCHIVED, DOC_DELETED, DOC_UPDATED, DOC_UPLOADED, DOC_VERSION, DOC_VERSION_DELETED
from app.core.files import _read_limited, add_link, path_for, save_bytes
from app.core.logging import log_scope, logger
from app.core.models import FileLink, StoredFile
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int
from app.modules.documents.extract import ERROR, OK, extract_bytes, status_label
from app.modules.documents.models import Document, DocumentVersion
from app.modules.projects.service import touch_project


def list_documents(session: Session, project_id: int, include_archived: bool) -> dict:
    limit = get_int("documents", "list.limit", project_id=project_id)
    query = select(Document).where(Document.project_id == project_id)
    if not include_archived:
        query = query.where(Document.archived.is_(False))
    rows = session.scalars(query.order_by(Document.updated_at.desc(), Document.id.desc()).limit(limit)).all()
    return {"items": [_brief(session, row) for row in rows]}


def create_document(
    session: Session,
    project_id: int,
    user_id: int,
    upload: UploadFile,
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


def delete_document(session: Session, project_id: int, user_id: int, document_id: int) -> None:
    document = _document(session, project_id, document_id)
    ids = [row.id for row in _versions(session, document.id)]
    _drop_links(session, ids)
    session.delete(document)
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


def document_text(session: Session, project_id: int, document_id: int) -> dict:
    document = _document(session, project_id, document_id)
    current = _current(session, document.id)
    text = current.extracted_text if current is not None else ""
    return {"text": text, "extract_status": current.extract_status if current else "", "chars": len(text)}


def dashboard_provider(session: Session, project_id: int, user_id: int | None, limits: dict) -> dict:
    limit = int(limits.get("recent_documents") or 1)
    rows = session.scalars(
        select(Document)
        .where(Document.project_id == project_id, Document.archived.is_(False))
        .order_by(Document.updated_at.desc(), Document.id.desc())
        .limit(limit)
    ).all()
    return {
        "recent_documents": [
            {"id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat()} for row in rows
        ]
    }


def search_provider(session: Session, project_id: int, user_id: int | None, query: str, limit: int) -> list[dict]:
    needle = query.casefold()
    statement = select(Document).where(Document.project_id == project_id)
    if not get_bool("documents", "search.include_archived", project_id=project_id):
        statement = statement.where(Document.archived.is_(False))
    documents = session.scalars(statement.order_by(Document.updated_at.desc(), Document.id.desc())).all()
    if not documents:
        return []
    include_all = get_bool("documents", "search.include_all_versions", project_id=project_id)
    versions = _versions_for(session, [row.id for row in documents])
    snippet_limit = get_int("documents", "search.snippet_chars", project_id=project_id)
    found = []
    for document in documents:
        own = [row for row in versions.get(document.id, [])]
        if not include_all and own:
            own = [max(own, key=lambda item: item.version_number)]
        snippet = _match(document, own, needle, snippet_limit)
        if snippet is None:
            continue
        found.append({"id": document.id, "title": document.title, "snippet": snippet})
        if len(found) >= limit:
            break
    return found


def retry_extract() -> None:
    batch = get_int("documents", "extract.retry_batch")
    maximum = get_int("documents", "extract.retry_max")
    with session_scope() as session:
        rows = session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.extract_status == ERROR)
            .where(DocumentVersion.extract_attempts < maximum)
            .order_by(DocumentVersion.id)
            .limit(batch)
        ).all()
        for row in rows:
            document = session.get(Document, row.document_id)
            project_id = document.project_id if document is not None else None
            _retry_one(session, row, project_id, maximum)
    if rows:
        with log_scope("documents", "extract"):
            logger.info("extract retry count={}", len(rows))


def ensure_parsers() -> None:
    import docx
    import fitz
    import openpyxl

    if docx is None or fitz is None or openpyxl is None:
        raise RuntimeError("парсеры документов не загрузились")


def _retry_one(session: Session, row: DocumentVersion, project_id: int | None, maximum: int) -> None:
    try:
        stored = session.get(StoredFile, row.file_id)
        path = path_for(stored.sha256) if stored is not None else None
        if stored is None or path is None or not path.is_file():
            row.extract_attempts = maximum
            row.extract_error = _short_error("Файл не найден на диске")
            return
        text, status, error = extract_bytes(stored.original_name, path.read_bytes(), project_id)
    except Exception as exc:
        row.extract_attempts = row.extract_attempts + 1
        row.extract_error = _short_error(str(exc) or "ошибка разбора")
        logger.warning("extract retry failed version={} error={}", row.id, row.extract_error)
        return
    row.extracted_text = text
    row.extract_status = status
    row.extract_error = error
    row.extract_attempts = row.extract_attempts + 1
    if status == OK:
        with log_scope("documents", "extract"):
            logger.info("extract retry ok version={} chars={}", row.id, len(text))


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


def _ensure_room(session: Session, document: Document) -> None:
    limit = get_int("documents", "versions.max_count", project_id=document.project_id)
    count = session.scalar(
        select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == document.id)
    )
    if int(count or 0) >= limit:
        raise HTTPException(status_code=400, detail="Версий уже " + str(limit))


def _next_number(session: Session, document_id: int) -> int:
    current = session.scalar(
        select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document_id)
    )
    return int(current or 0) + 1


def _document(session: Session, project_id: int, document_id: int) -> Document:
    row = session.get(Document, document_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return row


def _versions(session: Session, document_id: int) -> list[DocumentVersion]:
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        ).all()
    )


def _versions_for(session: Session, document_ids: list[int]) -> dict[int, list[DocumentVersion]]:
    if not document_ids:
        return {}
    rows = session.scalars(select(DocumentVersion).where(DocumentVersion.document_id.in_(document_ids))).all()
    grouped: dict[int, list[DocumentVersion]] = {}
    for row in rows:
        grouped.setdefault(row.document_id, []).append(row)
    return grouped


def _current(session: Session, document_id: int) -> DocumentVersion | None:
    return session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    ).first()


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


def _match(document: Document, versions: list[DocumentVersion], needle: str, limit: int) -> str | None:
    title_hit = needle in (document.title or "").casefold()
    note_hit = needle in (document.note or "").casefold()
    text_hit = ""
    for row in versions:
        body = row.extracted_text or ""
        if needle in body.casefold():
            text_hit = _snippet(body, needle, limit)
            break
        version_note = row.note or ""
        if needle in version_note.casefold() and not text_hit:
            text_hit = _snippet(version_note, needle, limit)
    if not title_hit and not note_hit and not text_hit:
        return None
    if text_hit:
        return text_hit
    if note_hit:
        return _snippet(document.note or "", needle, limit)
    return ""


def _snippet(text: str, needle: str, limit: int) -> str:
    folded = text.casefold()
    position = folded.find(needle)
    if position < 0:
        chunk = text[:limit]
    else:
        start = max(0, position - limit // 3)
        chunk = text[start : start + limit]
        if start:
            chunk = "…" + chunk
    chunk = " ".join(chunk.split())
    if len(chunk) > limit:
        return chunk[:limit] + "…"
    return chunk


def _clean_title(title: str, fallback_name: str) -> str:
    text = (title or "").strip()
    if not text:
        text = Path(fallback_name or "").stem.strip() or (fallback_name or "").strip()
    limit = get_int("documents", "title.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Укажите название")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Название длиннее " + str(limit) + " символов")
    return text


def _clean_note(note: str | None, key: str) -> str:
    text = note or ""
    limit = get_int("documents", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Текст длиннее " + str(limit) + " символов")
    return text


def _drop_links(session: Session, version_ids: list[int]) -> None:
    if not version_ids:
        return
    session.execute(
        delete(FileLink).where(
            FileLink.module == "documents",
            FileLink.entity_type == "document_version",
            FileLink.entity_id.in_(version_ids),
        )
    )


def _short_error(message: str) -> str:
    limit = get_int("documents", "extract.error.max_length")
    if len(message) > limit:
        return message[:limit]
    return message
