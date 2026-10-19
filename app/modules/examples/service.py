from __future__ import annotations

import mimetypes

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.versioning import check_version
from app.core.files import _read_limited, add_link, save_bytes
from app.core.events_catalog import EXAMPLE_CREATED, EXAMPLE_DELETED, EXAMPLE_FILE, EXAMPLE_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.models import FileLink, StoredFile
from app.core.settings_store import get, get_bool, get_int, get_str
from app.modules.examples.models import Example, ExampleTag, ExampleTagLink
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


def import_file(session: Session, project_id: int, user_id: int, upload, note: str) -> dict:
    filename = (upload.filename or "").strip() or "файл"
    created = create_example(
        session,
        project_id,
        user_id,
        {"title": filename, "body": "", "note": note or "", "language": "other", "pinned": False, "tags": []},
    )
    add_file(session, project_id, user_id, created["id"], upload)
    return get_example(session, project_id, created["id"])


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
    session.execute(
        delete(FileLink).where(
            FileLink.module == "examples",
            FileLink.entity_type == "example",
            FileLink.entity_id == row.id,
        )
    )
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


def list_tags(session: Session, project_id: int) -> dict:
    rows = session.scalars(
        select(ExampleTag).where(ExampleTag.project_id == project_id).order_by(ExampleTag.name)
    ).all()
    return {"items": [{"id": row.id, "name": row.name} for row in rows]}


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


def _example(session: Session, project_id: int, example_id: int) -> Example:
    row = session.get(Example, example_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Пример не найден")
    return row


def _brief(row: Example, tags: list[dict], file_count: int, project_id: int) -> dict:
    preview_limit = get_int("examples", "preview.max_chars", project_id=project_id)
    body = row.body or ""
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "note": row.note or "",
        "language": row.language or "",
        "language_label": _language_label(row.language, project_id),
        "pinned": bool(row.pinned),
        "archived": bool(row.archived),
        "preview": body[:preview_limit],
        "preview_truncated": len(body) > preview_limit,
        "tags": tags,
        "file_count": file_count,
        "files": [],
        "updated_at": row.updated_at.isoformat(),
        "created_at": row.created_at.isoformat(),
    }


def _full(session: Session, row: Example) -> dict:
    tags = _tags_for(session, [row.id]).get(row.id, [])
    counts = _file_counts(session, row.project_id, [row.id])
    payload = _brief(row, tags, counts.get(row.id, 0), row.project_id)
    payload["body"] = row.body or ""
    payload["files"] = _files(session, row.id)
    payload["languages"] = _languages(row.project_id)
    payload["tag_separator"] = get_str("examples", "tag.separator")
    return payload


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


def _ensure_file_room(session: Session, row: Example) -> None:
    limit = get_int("examples", "files.max_count", project_id=row.project_id)
    count = session.scalar(
        select(func.count())
        .select_from(FileLink)
        .where(FileLink.module == "examples", FileLink.entity_type == "example", FileLink.entity_id == row.id)
    )
    if int(count or 0) >= limit:
        raise HTTPException(status_code=400, detail="Файлов уже " + str(limit))


def _languages(project_id: int) -> list[dict]:
    raw = get("examples", "languages", project_id=project_id)
    items: list[dict] = []
    if not isinstance(raw, list):
        return items
    for item in raw:
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            code = str(item["id"]).strip()
            label = str(item.get("label") or code).strip() or code
            items.append({"id": code, "label": label})
        elif isinstance(item, str) and item.strip():
            items.append({"id": item.strip(), "label": item.strip()})
    return items


def _language_label(language: str, project_id: int) -> str:
    for item in _languages(project_id):
        if item["id"] == language:
            return item["label"]
    return language or ""


def _clean_language(value: str | None, project_id: int) -> str:
    text = (value or "").strip()
    if not text:
        text = get_str("examples", "language.default", project_id=project_id).strip()
    limit = get_int("examples", "language.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Язык длиннее " + str(limit) + " символов")
    if not text:
        return ""
    known = {item["id"] for item in _languages(project_id)}
    allow_custom = get_bool("examples", "language.allow_custom", project_id=project_id)
    if known and text not in known and not allow_custom:
        raise HTTPException(status_code=400, detail="Язык не из списка")
    return text


def _clean_title(title: str) -> str:
    text = (title or "").strip()
    limit = get_int("examples", "title.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Укажите название")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Название длиннее " + str(limit) + " символов")
    return text


def _clean_body(body: str, project_id: int) -> str:
    text = body or ""
    limit = get_int("examples", "body.max_length", project_id=project_id)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Текст длиннее " + str(limit) + " символов")
    if get_bool("examples", "body.required", project_id=project_id) and not text.strip():
        raise HTTPException(status_code=400, detail="Укажите текст примера")
    return text


def _clean_note(note: str) -> str:
    text = note or ""
    limit = get_int("examples", "note.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Заметка длиннее " + str(limit) + " символов")
    return text


def _clean_tag_names(names: list[str], project_id: int) -> list[str]:
    separator = get_str("examples", "tag.separator")
    limit = get_int("examples", "tag.name.max_length")
    maximum = get_int("examples", "tag.max_count", project_id=project_id)
    pieces: list[str] = []
    for name in names:
        raw = name or ""
        chunks = raw.split(separator) if separator else [raw]
        pieces.extend(chunks)
    result: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        text = piece.strip()
        if not text:
            continue
        if len(text) > limit:
            raise HTTPException(status_code=400, detail="Метка длиннее " + str(limit) + " символов")
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    if len(result) > maximum:
        raise HTTPException(status_code=400, detail="Меток больше " + str(maximum))
    return result


def _query_needle(query: str, project_id: int) -> str:
    text = (query or "").strip()
    minimum = get_int("examples", "list.query.min_length", project_id=project_id)
    if text and len(text) < minimum:
        raise HTTPException(status_code=400, detail="Фильтр короче " + str(minimum) + " символов")
    return text.casefold()


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
