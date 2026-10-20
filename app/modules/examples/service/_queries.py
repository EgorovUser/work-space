"""Приватные выборки примеров: строка по id, файлы, метки, потолок файлов."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.entities import owned_row
from app.core.models import FileLink, StoredFile
from app.core.settings_store import get_int
from app.modules.examples.models import Example, ExampleTag, ExampleTagLink


def _example(session: Session, project_id: int, example_id: int) -> Example:
    # У примеров нет корзины — удаление окончательное, поэтому без проверок
    # мягкого удаления (см. app/core/entities.py).
    return owned_row(
        session,
        Example,
        project_id,
        example_id,
        label="Пример",
        not_found="Пример не найден",
    )


def _files(session: Session, example_id: int) -> list[dict]:
    rows = session.execute(
        select(FileLink, StoredFile)
        .join(StoredFile, StoredFile.id == FileLink.file_id)
        .where(FileLink.module == "examples", FileLink.entity_type == "example", FileLink.entity_id == example_id)
        .order_by(FileLink.id)
    ).all()
    return [
        {
            "id": link.id,
            "file_id": stored.id,
            "original_name": stored.original_name,
            "size": stored.size,
        }
        for link, stored in rows
    ]


def _file_counts(session: Session, project_id: int, example_ids: list[int]) -> dict[int, int]:
    if not example_ids:
        return {}
    rows = session.execute(
        select(FileLink.entity_id, func.count())
        .where(
            FileLink.project_id == project_id,
            FileLink.module == "examples",
            FileLink.entity_type == "example",
            FileLink.entity_id.in_(example_ids),
        )
        .group_by(FileLink.entity_id)
    ).all()
    return {int(entity_id): int(count) for entity_id, count in rows}


def _tags_for(session: Session, example_ids: list[int]) -> dict[int, list[dict]]:
    if not example_ids:
        return {}
    rows = session.execute(
        select(ExampleTagLink.example_id, ExampleTag.id, ExampleTag.name)
        .join(ExampleTag, ExampleTag.id == ExampleTagLink.tag_id)
        .where(ExampleTagLink.example_id.in_(example_ids))
        .order_by(ExampleTag.name)
    ).all()
    grouped: dict[int, list[dict]] = {}
    for example_id, tag_id, name in rows:
        grouped.setdefault(int(example_id), []).append({"id": int(tag_id), "name": name})
    return grouped


def _ensure_file_room(session: Session, row: Example) -> None:
    limit = get_int("examples", "files.max_count", project_id=row.project_id)
    count = session.scalar(
        select(func.count())
        .select_from(FileLink)
        .where(FileLink.module == "examples", FileLink.entity_type == "example", FileLink.entity_id == row.id)
    )
    if int(count or 0) >= limit:
        raise HTTPException(status_code=400, detail="Файлов уже " + str(limit))
