"""Фоновые задачи документов: повтор разбора неудачных версий, проверка парсеров."""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import session_scope
from app.core.files import path_for
from app.core.logging import log_scope, logger
from app.core.models import StoredFile
from app.core.settings_store import get_int
from app.modules.documents.extract import ERROR, OK, extract_bytes
from app.modules.documents.models import Document, DocumentVersion


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


def _retry_one(session, row: DocumentVersion, project_id: int | None, maximum: int) -> None:
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


def _short_error(message: str) -> str:
    limit = get_int("documents", "extract.error.max_length")
    if len(message) > limit:
        return message[:limit]
    return message
