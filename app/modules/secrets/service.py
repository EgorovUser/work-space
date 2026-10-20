from __future__ import annotations

from secrets import choice as random_choice

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.versioning import check_version
from app.core.events_catalog import SECRET_CREATED, SECRET_DELETED, SECRET_OPENED, SECRET_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get, get_bool, get_int, get_str
from app.modules.projects.models import Project
from app.modules.projects.service import touch_project
from app.modules.secrets import crypto
from app.modules.secrets.models import Secret, SecretRevision


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


def generate_secret(project_id: int) -> dict:
    length = get_int("secrets", "generator.length", project_id=project_id)
    alphabet = _alphabet(project_id)
    if not alphabet:
        raise HTTPException(status_code=400, detail="Алфавит генератора пуст")
    value = "".join(random_choice(alphabet) for _ in range(length))
    with log_scope("secrets", "generate"):
        logger.info("secret generated length={}", length)
    return {"secret": value}


def list_revisions(session: Session, project_id: int, secret_id: int) -> dict:
    """История значений секрета — свежие снимки сверху.

    Значения не расшифровываются: только признаки (был ли пароль/логин/
    ссылка) и список полей, которые изменились в том изменении, — сравнение
    идёт с следующим по свежести состоянием (для самого свежего снимка —
    с текущей строкой).
    """
    row = _row(session, project_id, secret_id)
    keep = _keep_revisions(project_id)
    revisions = list(
        session.scalars(
            select(SecretRevision)
            .where(SecretRevision.secret_id == row.id)
            .order_by(SecretRevision.id.desc())
            .limit(keep)
        ).all()
    )
    items = []
    newer = row  # с чем сравниваем: текущая строка, затем более свежие снимки
    for revision in revisions:
        items.append(
            {
                "id": revision.id,
                "created_at": revision.created_at.isoformat(),
                "changed": _diff_fields(newer, revision),
                "has_secret": bool(revision.secret_enc),
                "has_username": bool(revision.username_enc),
                "has_url": bool(revision.url_enc),
            }
        )
        newer = revision
    return {"items": items}


def reveal_revision(session: Session, project_id: int, user_id: int, secret_id: int, revision_id: int) -> dict:
    """Прежнее значение секрета — как обычный reveal: событие и лог."""
    row = _row(session, project_id, secret_id)
    revision = _revision_row(session, row.id, revision_id)
    value = _unpack(revision.secret_enc, row.id)
    with log_scope("secrets", "reveal-revision", user_id=user_id):
        logger.info("secret revision revealed id={} secret={}", revision.id, row.id)
    enqueue(
        session,
        SECRET_OPENED,
        {"title": "Открыта прежняя версия секрета", "subject": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/secrets/" + str(row.id)},
        user_id=user_id,
    )
    return {"secret": value}


def restore_revision(session: Session, project_id: int, user_id: int, secret_id: int, revision_id: int) -> dict:
    """Откат к снимку — не разрушающий.

    Текущие значения сначала сами становятся снимком, потом в строку
    возвращаются значения из выбранной версии: «Вернуть» можно жать
    туда-обратно сколько угодно. Идентификатор нового снимка возвращается
    фронту — для кнопки «Отменить» у отката.
    """
    row = _row(session, project_id, secret_id)
    revision = _revision_row(session, row.id, revision_id)
    created = None
    if _diff_fields(row, revision):
        created = _add_revision(session, row, user_id)
        row.username_enc = revision.username_enc
        row.url_enc = revision.url_enc
        row.secret_enc = revision.secret_enc
        row.updated_at = utcnow()
        touch_project(session, project_id)
        session.flush()
        enqueue(
            session,
            SECRET_UPDATED,
            {"title": "Возвращена прежняя версия секрета", "subject": row.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/secrets/" + str(row.id)},
            user_id=user_id,
        )
        with log_scope("secrets", "restore-revision", user_id=user_id):
            logger.info("secret revision restored id={} secret={}", revision.id, row.id)
    else:
        with log_scope("secrets", "restore-revision", user_id=user_id):
            logger.info("secret revision restore no-op id={} secret={}", revision.id, row.id)
    payload = _detail(session, row)
    payload["revision_id"] = created.id if created else None
    return payload


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


def _row(session: Session, project_id: int, secret_id: int, in_trash: bool = False) -> Secret:
    row = session.get(Secret, secret_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Секрет не найден")
    if in_trash and row.deleted_at is None:
        raise HTTPException(status_code=404, detail="Секрет не в корзине")
    if not in_trash and row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Секрет удалён в корзину")
    return row


def _revision_row(session: Session, secret_id: int, revision_id: int) -> SecretRevision:
    row = session.get(SecretRevision, revision_id)
    if row is None or row.secret_id != secret_id:
        raise HTTPException(status_code=404, detail="Версия секрета не найдена")
    return row


def _keep_revisions(project_id: int) -> int:
    value = get_int("secrets", "history.keep_revisions", project_id=project_id)
    return value if value and value > 0 else 1


def _snapshot_if_changing(
    session: Session,
    row: Secret,
    user_id: int,
    new_username: str | None,
    new_url: str | None,
    new_secret: str | None,
) -> SecretRevision | None:
    """Снимок прежнего состояния, если меняется пароль, логин или ссылка.

    Сравниваются очищенные новые значения с расшифрованными текущими —
    правки без реальных изменений историю не засоряют. Нечитаемое
    (потерян ключ) текущее значение считается «меняется»: снимок сохранит
    шифротекст как есть, хуже не станет.
    """
    if new_username is None and new_url is None and new_secret is None:
        return None
    changed = (
        (new_secret is not None and new_secret != _soft_decrypt(row.secret_enc))
        or (new_username is not None and new_username != _soft_decrypt(row.username_enc))
        or (new_url is not None and new_url != _soft_decrypt(row.url_enc))
    )
    if not changed:
        return None
    return _add_revision(session, row, user_id)


def _add_revision(session: Session, row: Secret, user_id: int) -> SecretRevision:
    """Записывает снимок текущего состояния и подрезает хвост истории."""
    revision = SecretRevision(
        secret_id=row.id,
        username_enc=row.username_enc or "",
        url_enc=row.url_enc or "",
        secret_enc=row.secret_enc or "",
        created_by=user_id,
        created_at=utcnow(),
    )
    session.add(revision)
    session.flush()
    _prune_revisions(session, row.id, row.project_id)
    return revision


def _prune_revisions(session: Session, secret_id: int, project_id: int) -> None:
    keep = _keep_revisions(project_id)
    ids = list(
        session.scalars(
            select(SecretRevision.id)
            .where(SecretRevision.secret_id == secret_id)
            .order_by(SecretRevision.id.desc())
        ).all()
    )
    stale = ids[keep:]
    if stale:
        session.execute(delete(SecretRevision).where(SecretRevision.id.in_(stale)))


def _soft_decrypt(token: str) -> str | None:
    if not token:
        return ""
    try:
        return crypto.decrypt(token)
    except Exception:
        return None


def _diff_fields(a: Secret | SecretRevision, b: Secret | SecretRevision) -> list[str]:
    """Какие важные поля различаются между двумя состояниями (коды полей)."""
    changed = []
    if _soft_decrypt(a.secret_enc) != _soft_decrypt(b.secret_enc):
        changed.append("secret")
    if _soft_decrypt(a.username_enc) != _soft_decrypt(b.username_enc):
        changed.append("username")
    if _soft_decrypt(a.url_enc) != _soft_decrypt(b.url_enc):
        changed.append("url")
    return changed


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


def _pack(text: str) -> str:
    try:
        return crypto.encrypt(text)
    except Exception as exc:
        logger.warning("secret encrypt failed")
        raise HTTPException(status_code=500, detail="Не удалось сохранить секрет") from exc


def _unpack(token: str, secret_id: int) -> str:
    try:
        return crypto.decrypt(token)
    except ValueError:
        logger.warning("secret decrypt failed id={}", secret_id)
        raise HTTPException(status_code=500, detail="Не удалось прочитать секрет")


def _alphabet(project_id: int) -> str:
    chunks = []
    if get_bool("secrets", "generator.lowercase", project_id=project_id):
        chunks.append(get_str("secrets", "generator.lowercase_chars"))
    if get_bool("secrets", "generator.uppercase", project_id=project_id):
        chunks.append(get_str("secrets", "generator.uppercase_chars"))
    if get_bool("secrets", "generator.digits", project_id=project_id):
        chunks.append(get_str("secrets", "generator.digits_chars"))
    if get_bool("secrets", "generator.symbols", project_id=project_id):
        chunks.append(get_str("secrets", "generator.symbols_chars"))
    excluded = set(get_str("secrets", "generator.exclude", project_id=project_id))
    seen: list[str] = []
    for char in "".join(chunks):
        if char in excluded or char in seen:
            continue
        seen.append(char)
    return "".join(seen)


def _kinds(project_id: int) -> list[dict]:
    raw = get("secrets", "kinds", project_id=project_id)
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


def _kind_label(kind: str, project_id: int) -> str:
    for item in _kinds(project_id):
        if item["id"] == kind:
            return item["label"]
    return kind or ""


def _clean_kind(value: str | None, project_id: int) -> str:
    text = (value or "").strip()
    if not text:
        text = get_str("secrets", "kind.default", project_id=project_id).strip()
    limit = get_int("secrets", "kind.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Вид длиннее " + str(limit) + " символов")
    if not text:
        return ""
    known = {item["id"] for item in _kinds(project_id)}
    if known and text not in known and not get_bool("secrets", "kind.allow_custom", project_id=project_id):
        raise HTTPException(status_code=400, detail="Вид не из списка")
    return text


def _clean_title(title: str) -> str:
    text = (title or "").strip()
    limit = get_int("secrets", "title.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Укажите название")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Название длиннее " + str(limit) + " символов")
    return text


def _clean_limit(value: str, key: str, strip: bool) -> str:
    text = value or ""
    if strip:
        text = text.strip()
    limit = get_int("secrets", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Текст длиннее " + str(limit) + " символов")
    return text


def _clean_secret(value: str, project_id: int, required: bool) -> str:
    text = value or ""
    limit = get_int("secrets", "secret.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Секрет длиннее " + str(limit) + " символов")
    must = required and get_bool("secrets", "secret.required", project_id=project_id)
    if must and not text:
        raise HTTPException(status_code=400, detail="Укажите секрет")
    if not required and not text and get_bool("secrets", "secret.required", project_id=project_id):
        raise HTTPException(status_code=400, detail="Секрет нельзя очистить")
    return text


def _query_needle(query: str, project_id: int) -> str:
    text = (query or "").strip()
    minimum = get_int("secrets", "list.query.min_length", project_id=project_id)
    if text and len(text) < minimum:
        raise HTTPException(status_code=400, detail="Фильтр короче " + str(minimum) + " символов")
    return text.casefold()
