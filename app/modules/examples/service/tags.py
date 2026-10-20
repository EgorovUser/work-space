"""Метки примеров: список проекта, синхронизация у примера, уборка сирот."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.examples.models import ExampleTag, ExampleTagLink
from app.modules.examples.service._validators import _clean_tag_names


def list_tags(session: Session, project_id: int) -> dict:
    rows = session.scalars(
        select(ExampleTag).where(ExampleTag.project_id == project_id).order_by(ExampleTag.name)
    ).all()
    return {"items": [{"id": row.id, "name": row.name} for row in rows]}


def _sync_tags(session: Session, project_id: int, example_id: int, names: list[str]) -> bool:
    cleaned = _clean_tag_names(names, project_id)
    existing = list(session.scalars(select(ExampleTag).where(ExampleTag.project_id == project_id)).all())
    by_fold = {row.name.casefold(): row for row in existing}
    wanted: list[ExampleTag] = []
    for name in cleaned:
        tag = by_fold.get(name.casefold())
        if tag is None:
            tag = ExampleTag(project_id=project_id, name=name)
            session.add(tag)
            session.flush()
            by_fold[name.casefold()] = tag
        wanted.append(tag)
    current = list(session.scalars(select(ExampleTagLink).where(ExampleTagLink.example_id == example_id)).all())
    wanted_ids = {tag.id for tag in wanted}
    have = {link.tag_id for link in current}
    changed = wanted_ids != have
    for link in current:
        if link.tag_id not in wanted_ids:
            session.delete(link)
    for tag in wanted:
        if tag.id not in have:
            session.add(ExampleTagLink(example_id=example_id, tag_id=tag.id))
    session.flush()
    _drop_orphan_tags(session, project_id)
    return changed


def _drop_orphan_tags(session: Session, project_id: int) -> None:
    tags = list(session.scalars(select(ExampleTag).where(ExampleTag.project_id == project_id)).all())
    for tag in tags:
        used = session.scalar(
            select(func.count()).select_from(ExampleTagLink).where(ExampleTagLink.tag_id == tag.id)
        )
        if not int(used or 0):
            session.delete(tag)
    session.flush()
