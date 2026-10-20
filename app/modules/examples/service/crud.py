"""Примеры: список, создание, правка, удаление (окончательное), поиск."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.versioning import check_version
from app.core.events_catalog import EXAMPLE_CREATED, EXAMPLE_DELETED, EXAMPLE_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int, get_str
from app.modules.examples.models import Example
from app.modules.examples.service._queries import _example, _file_counts, _files, _tags_for
from app.modules.examples.service._serialize import _brief, _full
from app.modules.examples.service._validators import (
    _clean_body,
    _clean_language,
    _clean_note,
    _clean_title,
    _query_needle,
)
from app.modules.examples.service.catalog import _languages
from app.modules.examples.service.files import _drop_example_links
from app.modules.examples.service.tags import _drop_orphan_tags, _sync_tags
from app.modules.projects.service import touch_project


def list_examples(
    session: Session,
    project_id: int,
    include_archived: bool,
    language: str,
    query: str,
) -> dict:
    needle = _query_needle(query, project_id)
    language_filter = (language or "").strip()
    scan = get_int("examples", "list.scan_limit", project_id=project_id)
    limit = get_int("examples", "list.limit", project_id=project_id)
    statement = select(Example).where(Example.project_id == project_id)
    if not include_archived:
        statement = statement.where(Example.archived.is_(False))
    if language_filter:
        statement = statement.where(Example.language == language_filter)
    rows = list(session.scalars(statement.order_by(Example.id.desc()).limit(scan)).all())
    if needle:
        tags = _tags_for(session, [row.id for row in rows])
        rows = [row for row in rows if _matches(row, tags.get(row.id, []), needle)]
    rows.sort(key=lambda row: (0 if row.pinned else 1, -row.updated_at.timestamp(), -row.id))
    rows = rows[:limit]
    tags = _tags_for(session, [row.id for row in rows])
    counts = _file_counts(session, project_id, [row.id for row in rows])
    items = []
    for row in rows:
        item = _brief(row, tags.get(row.id, []), counts.get(row.id, 0), project_id)
        item["files"] = _files(session, row.id)
        items.append(item)
    return {
        "items": items,
        "languages": _languages(project_id),
        "tag_separator": get_str("examples", "tag.separator"),
    }


def create_example(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    now = utcnow()
    row = Example(
        project_id=project_id,
        title=_clean_title(fields.get("title") or ""),
        body=_clean_body(fields.get("body") or "", project_id),
        note=_clean_note(fields.get("note") or ""),
        language=_clean_language(fields.get("language"), project_id),
        pinned=bool(fields.get("pinned")),
        archived=False,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    _sync_tags(session, project_id, row.id, fields.get("tags") or [])
    touch_project(session, project_id)
    with log_scope("examples", "create", user_id=user_id):
        logger.info("example created id={} language={} chars={}", row.id, row.language, len(row.body or ""))
    enqueue(
        session,
        EXAMPLE_CREATED,
        {"title": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/examples/" + str(row.id)},
        user_id=user_id,
    )
    return _full(session, row)


def get_example(session: Session, project_id: int, example_id: int) -> dict:
    return _full(session, _example(session, project_id, example_id))


def update_example(session: Session, project_id: int, user_id: int, example_id: int, fields: dict) -> dict:
    row = _example(session, project_id, example_id)
    check_version(fields, row.updated_at, "Пример")
    changed = False
    if "title" in fields and fields["title"] is not None:
        title = _clean_title(fields["title"])
        if title != row.title:
            row.title = title
            changed = True
    if "body" in fields and fields["body"] is not None:
        body = _clean_body(fields["body"], project_id)
        if body != row.body:
            row.body = body
            changed = True
    if "note" in fields and fields["note"] is not None:
        note = _clean_note(fields["note"])
        if note != row.note:
            row.note = note
            changed = True
    if "language" in fields and fields["language"] is not None:
        language = _clean_language(fields["language"], project_id)
        if language != row.language:
            row.language = language
            changed = True
    if "pinned" in fields and fields["pinned"] is not None:
        pinned = bool(fields["pinned"])
        if pinned != row.pinned:
            row.pinned = pinned
            changed = True
    if "archived" in fields and fields["archived"] is not None:
        archived = bool(fields["archived"])
        if archived != row.archived:
            row.archived = archived
            changed = True
    if "tags" in fields and fields["tags"] is not None:
        if _sync_tags(session, project_id, row.id, fields["tags"]):
            changed = True
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    if changed:
        enqueue(
            session,
            EXAMPLE_UPDATED,
            {"title": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/examples/" + str(row.id)},
            user_id=user_id,
        )
    with log_scope("examples", "update", user_id=user_id):
        logger.info("example updated id={} pinned={} archived={}", row.id, row.pinned, row.archived)
    return _full(session, row)


def delete_example(session: Session, project_id: int, user_id: int, example_id: int) -> None:
    row = _example(session, project_id, example_id)
    _drop_example_links(session, row.id)
    session.delete(row)
    session.flush()
    _drop_orphan_tags(session, project_id)
    touch_project(session, project_id)
    with log_scope("examples", "delete", user_id=user_id):
        logger.info("example deleted id={}", example_id)
    enqueue(
        session,
        EXAMPLE_DELETED,
        {"title": "Пример удалён", "subject": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/examples"},
        user_id=user_id,
    )


def search_provider(session: Session, project_id: int, user_id: int | None, query: str, limit: int) -> list[dict]:
    needle = query.casefold()
    statement = select(Example).where(Example.project_id == project_id)
    if not get_bool("examples", "search.include_archived", project_id=project_id):
        statement = statement.where(Example.archived.is_(False))
    rows = list(session.scalars(statement.order_by(Example.updated_at.desc())).all())
    tags = _tags_for(session, [row.id for row in rows])
    snippet_limit = get_int("examples", "search.snippet_chars", project_id=project_id)
    found = []
    for row in rows:
        if not _matches(row, tags.get(row.id, []), needle):
            continue
        found.append({"id": row.id, "title": row.title, "snippet": _snippet_for(row, tags.get(row.id, []), needle, snippet_limit)})
        if len(found) >= limit:
            break
    return found


def _matches(row: Example, tags: list[dict], needle: str) -> bool:
    hay = " ".join([row.title or "", row.note or "", row.body or "", " ".join(item["name"] for item in tags)])
    return needle in hay.casefold()


def _snippet_for(row: Example, tags: list[dict], needle: str, limit: int) -> str:
    if needle in (row.body or "").casefold():
        return _snippet(row.body or "", needle, limit)
    if needle in (row.note or "").casefold():
        return _snippet(row.note or "", needle, limit)
    if needle in " ".join(item["name"] for item in tags).casefold():
        return ", ".join(item["name"] for item in tags)
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
