"""Приватные выборки документов и версий: строка по id, версии, связи файлов."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.entities import owned_row
from app.core.models import FileLink
from app.modules.documents.models import Document, DocumentVersion


def _document(session: Session, project_id: int, document_id: int, in_trash: bool = False) -> Document:
    return owned_row(
        session,
        Document,
        project_id,
        document_id,
        in_trash=in_trash,
        label="Документ",
        not_found="Документ не найден",
        deleted_to_trash="Документ удалён в корзину",
    )


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


def _ensure_room(session: Session, document: Document) -> None:
    from app.core.settings_store import get_int

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
