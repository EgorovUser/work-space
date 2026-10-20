"""История значений секрета (патч O): снимки, просмотр, откат, подрезка.

Откат не разрушающий: текущие значения сначала сами становятся снимком,
потом в строку возвращаются значения из выбранной версии.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_catalog import SECRET_OPENED, SECRET_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_int
from app.modules.projects.service import touch_project
from app.modules.secrets.models import Secret, SecretRevision
from app.modules.secrets.service._queries import _revision_row, _row
from app.modules.secrets.service.values import _soft_decrypt, _unpack


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
    from app.modules.secrets.service.crud import _detail

    payload = _detail(session, row)
    payload["revision_id"] = created.id if created else None
    return payload


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


def _diff_fields(a, b) -> list[str]:
    """Какие важные поля различаются между двумя состояниями (коды полей)."""
    changed = []
    if _soft_decrypt(a.secret_enc) != _soft_decrypt(b.secret_enc):
        changed.append("secret")
    if _soft_decrypt(a.username_enc) != _soft_decrypt(b.username_enc):
        changed.append("username")
    if _soft_decrypt(a.url_enc) != _soft_decrypt(b.url_enc):
        changed.append("url")
    return changed
