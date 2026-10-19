"""Метки задач: список, создание, удаление."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import log_scope, logger
from app.modules.tasks.models import Tag, TaskTag
from app.modules.tasks.service._queries import _tag_out
from app.modules.tasks.service._validators import _clean


def list_tags(session: Session, project_id: int) -> list[dict]:
    rows = session.scalars(select(Tag).where(Tag.project_id == project_id).order_by(Tag.name.asc(), Tag.id.asc())).all()
    return [_tag_out(row) for row in rows]


def create_tag(session: Session, project_id: int, user_id: int, name: str) -> dict:
    text = _clean(name, "tag.name.max_length", "Укажите метку")
    rows = session.scalars(select(Tag).where(Tag.project_id == project_id)).all()
    if any(row.name.casefold() == text.casefold() for row in rows):
        raise HTTPException(status_code=400, detail="Такая метка уже есть")
    row = Tag(project_id=project_id, name=text)
    session.add(row)
    session.flush()
    with log_scope("tasks", "tag.create", user_id=user_id):
        logger.info("tag created id={} project={}", row.id, project_id)
    return _tag_out(row)


def delete_tag(session: Session, project_id: int, user_id: int, tag_id: int) -> None:
    row = session.get(Tag, tag_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Метка не найдена")
    for link in session.scalars(select(TaskTag).where(TaskTag.tag_id == row.id)).all():
        session.delete(link)
    session.delete(row)
    session.flush()
    with log_scope("tasks", "tag.delete", user_id=user_id):
        logger.info("tag deleted id={} project={}", tag_id, project_id)
