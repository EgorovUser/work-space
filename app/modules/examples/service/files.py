"""Файлы примера: прикрепление, открепление, импорт файла новым примером."""

from __future__ import annotations

import mimetypes

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_catalog import EXAMPLE_FILE
from app.core.files import _read_limited, add_link, save_bytes
from app.core.logging import log_scope, logger
from app.core.models import FileLink
from app.core.outbox import enqueue
from app.core.settings_store import get_int
from app.modules.examples.service._queries import _ensure_file_room, _example
from app.modules.examples.service._serialize import _full
from app.modules.projects.service import touch_project


def import_file(session: Session, project_id: int, user_id: int, upload, note: str) -> dict:
    from app.modules.examples.service.crud import create_example, get_example

    filename = (upload.filename or "").strip() or "файл"
    created = create_example(
        session,
        project_id,
        user_id,
        {"title": filename, "body": "", "note": note or "", "language": "other", "pinned": False, "tags": []},
    )
    add_file(session, project_id, user_id, created["id"], upload)
    return get_example(session, project_id, created["id"])


def add_file(session: Session, project_id: int, user_id: int, example_id: int, upload: UploadFile) -> dict:
    row = _example(session, project_id, example_id)
    _ensure_file_room(session, row)
    data = _read_limited(upload.file, get_int("core", "files.max_upload_mb") * 1024 * 1024)
    filename = upload.filename or "file"
    mime = upload.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    stored = save_bytes(session, data, filename, mime, user_id)
    add_link(
        session,
        stored.id,
        project_id=project_id,
        module="examples",
        entity_type="example",
        entity_id=row.id,
    )
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        EXAMPLE_FILE,
        {"title": row.title, "subject": stored.original_name, "project_id": project_id, "link": "/projects/" + str(project_id) + "/examples/" + str(row.id)},
        user_id=user_id,
    )
    with log_scope("examples", "attach", user_id=user_id):
        logger.info("example file id={} file={}", row.id, stored.id)
    return _full(session, row)


def delete_file(session: Session, project_id: int, user_id: int, example_id: int, link_id: int) -> None:
    row = _example(session, project_id, example_id)
    link = session.get(FileLink, link_id)
    if link is None or link.module != "examples" or link.entity_type != "example" or link.entity_id != row.id:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if link.project_id not in (None, project_id):
        raise HTTPException(status_code=404, detail="Файл не найден")
    session.delete(link)
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    with log_scope("examples", "attach.delete", user_id=user_id):
        logger.info("example file deleted id={} link={}", row.id, link_id)


def _drop_example_links(session: Session, example_id: int) -> None:
    session.execute(
        delete(FileLink).where(
            FileLink.module == "examples",
            FileLink.entity_type == "example",
            FileLink.entity_id == example_id,
        )
    )


__all__ = ["add_file", "delete_file", "import_file"]
