"""Секреты: списки (проектный и общий), CRUD, мягкое удаление, показ значения."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.versioning import check_version
from app.core.events_catalog import SECRET_CREATED, SECRET_DELETED, SECRET_OPENED, SECRET_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int
from app.modules.projects.models import Project
from app.modules.projects.service import touch_project
from app.modules.secrets.models import Secret, SecretRevision
from app.modules.secrets.service._queries import _row
from app.modules.secrets.service._validators import (
    _clean_kind,
    _clean_limit,
    _clean_secret,
    _clean_title,
    _query_needle,
)
from app.modules.secrets.service.catalog import _kind_label, _kinds
from app.modules.secrets.service.values import _pack, _unpack


def list_secrets(session: Session, project_id: int, include_archived: bool, query: str) -> dict:
    needle = _query_needle(query, project_id)
    scan = get_int("secrets", "list.scan_limit", project_id=project_id)
    limit = get_int("secrets", "list.limit", project_id=project_id)
    statement = select(Secret).where(
        Secret.project_id == project_id,
        # Секреты из корзины в списке не показываем (патч N).
        Secret.deleted_at.is_(None),
    )
    if not include_archived:
        statement = statement.where(Secret.archived.is_(False))
    rows = list(session.scalars(statement.order_by(Secret.updated_at.desc(), Secret.id.desc()).limit(scan)).all())
    if needle:
        rows = [row for row in rows if needle in (row.title or "").casefold()]
    rows = rows[:limit]
    return {"items": [_public(row, project_id) for row in rows], "kinds": _kinds(project_id)}


def list_all_secrets(session: Session, include_archived: bool, query: str) -> dict:
    """Общий список секретов всех проектов — для глобального раздела.

    Группы идут по проектам: активные первыми, дальше по алфавиту названий.
    Внутри проекта — свежие сверху, как и в проектном списке. Общий потолок
    берётся из secrets.list.global_limit: при переполнении список честно
    обрезается и об этом говорит флаг truncated.
    """
    needle = _query_needle(query, None)
    cap = get_int("secrets", "list.global_limit")
    statement = select(Project).order_by(Project.archived.asc(), func.lower(Project.name).asc(), Project.id.asc())
    if not include_archived:
        statement = statement.where(Project.archived.is_(False))
    groups: list[dict] = []
    total = 0
    truncated = False
    for project in session.scalars(statement).all():
        rows = _project_rows(session, project.id, include_archived, needle)
        if not rows:
            continue
        room = cap - total
        if room <= 0:
            truncated = True
            break
        if len(rows) > room:
            rows = rows[:room]
            truncated = True
        groups.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "project_archived": bool(project.archived),
                "items": [_public(row, project.id) for row in rows],
            }
        )
        total += len(rows)
    return {"groups": groups, "total": total, "truncated": truncated}


def create_secret(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    secret_text = _clean_secret(fields.get("secret") or "", project_id, required=True)
    now = utcnow()
    row = Secret(
        project_id=project_id,
        title=_clean_title(fields.get("title") or ""),
        kind=_clean_kind(fields.get("kind"), project_id),
        username_enc=_pack(_clean_limit(fields.get("username") or "", "username.max_length", strip=True)),
        url_enc=_pack(_clean_limit(fields.get("url") or "", "url.max_length", strip=True)),
        note_enc=_pack(_clean_limit(fields.get("note") or "", "note.max_length", strip=False)),
        secret_enc=_pack(secret_text),
        archived=False,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("secrets", "create", user_id=user_id):
        logger.info("secret created id={} has_secret={}", row.id, bool(row.secret_enc))
    enqueue(
        session,
        SECRET_CREATED,
        {"title": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/secrets/" + str(row.id)},
        user_id=user_id,
    )
    return _detail(session, row)


def get_secret(session: Session, project_id: int, secret_id: int) -> dict:
    return _detail(session, _row(session, project_id, secret_id))


def update_secret(session: Session, project_id: int, user_id: int, secret_id: int, fields: dict) -> dict:
    from app.modules.secrets.service.revisions import _snapshot_if_changing

    row = _row(session, project_id, secret_id)
    check_version(fields, row.updated_at, "Секрет")
    # Новые значения важные полей считаем заранее: сравнить с текущими и
    # решить, нужен ли снимок истории, до того как строка будет изменена.
    new_username = (
        _clean_limit(fields["username"], "username.max_length", strip=True)
        if "username" in fields and fields["username"] is not None
        else None
    )
    new_url = (
        _clean_limit(fields["url"], "url.max_length", strip=True)
        if "url" in fields and fields["url"] is not None
        else None
    )
    new_secret = (
        _clean_secret(fields["secret"], project_id, required=False)
        if "secret" in fields and fields["secret"] is not None
        else None
    )
    revision = _snapshot_if_changing(session, row, user_id, new_username, new_url, new_secret)
    if "title" in fields and fields["title"] is not None:
        row.title = _clean_title(fields["title"])
    if "kind" in fields and fields["kind"] is not None:
        row.kind = _clean_kind(fields["kind"], project_id)
    if "note" in fields and fields["note"] is not None:
        row.note_enc = _pack(_clean_limit(fields["note"], "note.max_length", strip=False))
    if new_username is not None:
        row.username_enc = _pack(new_username)
    if new_url is not None:
        row.url_enc = _pack(new_url)
    if new_secret is not None:
        row.secret_enc = _pack(new_secret)
    if "archived" in fields and fields["archived"] is not None:
        row.archived = bool(fields["archived"])
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        SECRET_UPDATED,
        {"title": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/secrets/" + str(row.id)},
        user_id=user_id,
    )
    with log_scope("secrets", "update", user_id=user_id):
        logger.info("secret updated id={} archived={} revision={}", row.id, row.archived, revision.id if revision else 0)
    payload = _detail(session, row)
    # Идентификатор снимка — фронту для кнопки «Отменить» сразу после
    # сохранения: один POST восстанавливает прежние значения.
    payload["revision_id"] = revision.id if revision else None
    return payload


def delete_secret(session: Session, project_id: int, user_id: int, secret_id: int) -> dict:
    """Мягкое удаление: секрет уходит в корзину (патч N).

    Зашифрованные значения остаются при записи — восстановление вернёт
    секрет целиком, без потери данных.
    """
    row = _row(session, project_id, secret_id)
    row.deleted_at = utcnow()
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        SECRET_DELETED,
        {"title": "Секрет удалён", "subject": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/secrets"},
        user_id=user_id,
    )
    with log_scope("secrets", "delete", user_id=user_id):
        logger.info("secret deleted id={}", secret_id)
    return {"id": row.id, "title": row.title, "deleted_at": row.deleted_at.isoformat()}


def restore_secret(session: Session, project_id: int, user_id: int, secret_id: int) -> dict:
    row = _row(session, project_id, secret_id, in_trash=True)
    row.deleted_at = None
    row.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        SECRET_UPDATED,
        {"title": "Секрет восстановлен", "subject": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/secrets/" + str(row.id)},
        user_id=user_id,
    )
    with log_scope("secrets", "restore", user_id=user_id):
        logger.info("secret restored id={}", secret_id)
    return _public(row, project_id)


def purge_secret(session: Session, project_id: int, user_id: int, secret_id: int) -> None:
    """Окончательное удаление — только из корзины."""
    row = _row(session, project_id, secret_id, in_trash=True)
    # Снимки удаляются вместе с секретом: чужие пароли в истории не
    # должны переживать сам секрет.
    session.execute(delete(SecretRevision).where(SecretRevision.secret_id == row.id))
    session.delete(row)
    touch_project(session, project_id)
    session.flush()
    with log_scope("secrets", "purge", user_id=user_id):
        logger.info("secret purged id={}", secret_id)


def reveal_secret(session: Session, project_id: int, user_id: int, secret_id: int) -> dict:
    row = _row(session, project_id, secret_id)
    value = _unpack(row.secret_enc, row.id)
    with log_scope("secrets", "reveal", user_id=user_id):
        logger.info("secret revealed id={}", row.id)
    enqueue(
        session,
        SECRET_OPENED,
        {"title": "Открыт секрет", "subject": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/secrets/" + str(row.id)},
        user_id=user_id,
    )
    return {"secret": value}


def search_provider(session: Session, project_id: int, user_id: int | None, query: str, limit: int) -> list[dict]:
    needle = query.casefold()
    statement = select(Secret).where(
        Secret.project_id == project_id,
        Secret.deleted_at.is_(None),
    )
    if not get_bool("secrets", "search.include_archived", project_id=project_id):
        statement = statement.where(Secret.archived.is_(False))
    rows = session.scalars(statement.order_by(Secret.updated_at.desc(), Secret.id.desc())).all()
    found = []
    for row in rows:
        if needle in (row.title or "").casefold():
            found.append({"id": row.id, "title": row.title})
        if len(found) >= limit:
            break
    return found


def _project_rows(session: Session, project_id: int, include_archived: bool, needle: str) -> list[Secret]:
    scan = get_int("secrets", "list.scan_limit", project_id=project_id)
    limit = get_int("secrets", "list.limit", project_id=project_id)
    statement = select(Secret).where(
        Secret.project_id == project_id,
        Secret.deleted_at.is_(None),
    )
    if not include_archived:
        statement = statement.where(Secret.archived.is_(False))
    rows = list(session.scalars(statement.order_by(Secret.updated_at.desc(), Secret.id.desc()).limit(scan)).all())
    if needle:
        rows = [row for row in rows if needle in (row.title or "").casefold()]
    return rows[:limit]


def _public(row: Secret, project_id: int) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "kind": row.kind or "",
        "kind_label": _kind_label(row.kind, project_id),
        "has_username": bool(row.username_enc),
        "has_url": bool(row.url_enc),
        "has_note": bool(row.note_enc),
        "has_secret": bool(row.secret_enc),
        "archived": bool(row.archived),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _detail(session: Session, row: Secret) -> dict:
    payload = _public(row, row.project_id)
    payload["username"] = _unpack(row.username_enc, row.id)
    payload["url"] = _unpack(row.url_enc, row.id)
    payload["note"] = _unpack(row.note_enc, row.id)
    payload["kinds"] = _kinds(row.project_id)
    return payload
