"""Поиск по документам для командной палитры: название, заметка, текст версий."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import get_bool, get_int
from app.core.text import snippet as _snippet
from app.modules.documents.models import Document, DocumentVersion
from app.modules.documents.service._queries import _versions_for


def search_provider(session: Session, project_id: int, user_id: int | None, query: str, limit: int) -> list[dict]:
    needle = query.casefold()
    statement = select(Document).where(
        Document.project_id == project_id,
        Document.deleted_at.is_(None),
    )
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
