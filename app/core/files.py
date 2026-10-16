from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.config import get as get_config
from app.core.db import get_db
from app.core.deps import require_project
from app.core.logging import log_scope, logger
from app.core.models import FileLink, StoredFile, User
from app.core.settings_store import get_int

router = APIRouter()


def path_for(sha256: str) -> Path:
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise HTTPException(status_code=404, detail="Файл не найден")
    return get_config().data_path() / "files" / sha256[:2] / sha256


def save_bytes(
    session: Session,
    data: bytes,
    original_name: str,
    mime_type: str,
    uploaded_by: int | None,
) -> StoredFile:
    max_bytes = get_int("core", "files.max_upload_mb") * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Файл слишком большой")
    name = _safe_name(original_name)
    _check_extension(name)
    digest = hashlib.sha256(data).hexdigest()
    existing = session.scalars(select(StoredFile).where(StoredFile.sha256 == digest)).one_or_none()
    if existing is not None:
        return existing
    _write_blob(digest, data)
    row = StoredFile(
        sha256=digest,
        original_name=name,
        mime_type=mime_type or "application/octet-stream",
        size=len(data),
        uploaded_by=uploaded_by,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        found = session.scalars(select(StoredFile).where(StoredFile.sha256 == digest)).one_or_none()
        if found is None:
            raise
        return found
    with log_scope("files", "save", user_id=uploaded_by):
        logger.info("file saved id={} sha={} size={}", row.id, digest, row.size)
    return row


def add_link(
    session: Session,
    file_id: int,
    *,
    project_id: int | None,
    module: str,
    entity_type: str,
    entity_id: int,
) -> FileLink:
    link = FileLink(
        file_id=file_id,
        project_id=project_id,
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    session.add(link)
    session.flush()
    return link


def healthcheck() -> None:
    folder = get_config().data_path() / "files"
    folder.mkdir(parents=True, exist_ok=True)
    probe = folder / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


@router.post("/api/files")
def upload(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    data = _read_limited(file.file, get_int("core", "files.max_upload_mb") * 1024 * 1024)
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    row = save_bytes(db, data, file.filename or "file", mime, user.id)
    return _file_out(row)


@router.get("/api/files/{file_id}")
def download(
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_user),
):
    row = db.get(StoredFile, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    path = path_for(row.sha256)
    if not path.is_file():
        with log_scope("files", "download"):
            logger.error("file missing id={} sha={}", row.id, row.sha256)
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    return FileResponse(path, filename=row.original_name, media_type=row.mime_type)


@router.get("/api/projects/{project_id}/files")
def list_project_files(
    project_id: int,
    db: Session = Depends(get_db),
    _project=Depends(require_project),
) -> dict:
    rows = db.scalars(
        select(StoredFile)
        .join(FileLink, FileLink.file_id == StoredFile.id)
        .where(FileLink.project_id == project_id)
        .distinct()
        .order_by(StoredFile.id.desc())
    ).all()
    return {"items": [_file_out(row) for row in rows]}


def _file_out(row: StoredFile) -> dict:
    return {
        "id": row.id,
        "sha256": row.sha256,
        "original_name": row.original_name,
        "mime_type": row.mime_type,
        "size": row.size,
    }


def _read_limited(source, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="Файл слишком большой")
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_name(original_name: str) -> str:
    name = Path(original_name or "file").name.strip() or "file"
    return name[:500]


def _check_extension(name: str) -> None:
    from app.core.settings_store import get

    allowed = get("core", "files.allowed_extensions")
    if not isinstance(allowed, list) or not allowed:
        return
    suffix = Path(name).suffix.lower().lstrip(".")
    normalized = [str(item).lower().lstrip(".") for item in allowed]
    if suffix not in normalized:
        raise HTTPException(status_code=400, detail="Тип файла не разрешён")


def _write_blob(digest: str, data: bytes) -> None:
    path = path_for(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
