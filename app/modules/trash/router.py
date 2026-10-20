"""Корзина (патч N): мягко удалённые записи задач, документов, секретов и RDP.

Модули сами решают, что значит «удалено» (колонка deleted_at), а здесь —
общая витрина: список по типам, восстановление, окончательное удаление
и фоновая очистка по retention-дням. Почта в корзину не попадает: у неё
есть свой архив, а мягкое удаление сломало бы уникальность UID при
повторном заборе с сервера.
"""

from __future__ import annotations

import math
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import registry
from app.core.auth import require_user
from app.core.db import get_db, session_scope, utcnow
from app.core.logging import log_scope, logger
from app.core.models import User
from app.core.counters import register_global_counters
from app.core.scheduler import register_job
from app.core.settings_store import get_int, register_defs
from app.modules.documents.models import Document
from app.modules.projects.models import Project
from app.modules.rdp.models import RdpConnection
from app.modules.secrets.models import Secret
from app.modules.tasks.models import Task

from .settings import DEFS

router = APIRouter()

# Что умеет лежать в корзине. restore/purge вызывают сервисы модулей —
# события, счётчики проектов и логи остаются консистентными.
_KINDS = ("tasks", "documents", "secrets", "rdp")

_LABELS = {
    "tasks": "Задачи",
    "documents": "Документы",
    "secrets": "Секреты",
    "rdp": "RDP-подключения",
}

_MODELS = {
    "tasks": Task,
    "documents": Document,
    "secrets": Secret,
    "rdp": RdpConnection,
}


def _kind(kind: str) -> str:
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail="Такого типа в корзине нет")
    return kind


def global_counts(session: Session, user_id: int | None = None) -> dict:
    """Счётчик рельсы «Корзина» (патч AA): сколько мягко удалённого лежит внутри.

    Провайдер для хаба ``app/core/counters.py``. Учитываются только
    включённые модули — как и в самой витрине корзины.
    """
    total = 0
    for kind in _KINDS:
        if not registry.is_enabled(kind):
            continue
        model = _MODELS[kind]
        value = session.scalar(
            select(func.count()).select_from(model).where(model.deleted_at.is_not(None))
        )
        total += int(value or 0)
    return {"trash_total": total}


@router.get("/api/trash")
def list_trash(db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    days = get_int("trash", "retention_days")
    now = utcnow()
    groups = []
    names = {row.id: row.name for row in db.scalars(select(Project)).all()}
    for kind in _KINDS:
        if not registry.is_enabled(kind):
            continue
        model = _MODELS[kind]
        rows = list(
            db.scalars(
                select(model)
                .where(model.deleted_at.is_not(None))
                .order_by(model.deleted_at.desc(), model.id.desc())
                .limit(200)
            ).all()
        )
        if not rows:
            continue
        groups.append(
            {
                "id": kind,
                "label": _LABELS[kind],
                "items": [
                    {
                        "id": row.id,
                        "project_id": row.project_id,
                        "project_name": names.get(row.project_id, ""),
                        "title": row.title if kind != "rdp" else row.name,
                        "deleted_at": row.deleted_at.isoformat(),
                        # Сколько проживёт до очистки джобой (патч P).
                        "days_left": _days_left(now, row.deleted_at, days),
                    }
                    for row in rows
                ],
            }
        )
    return {"groups": groups, "retention_days": days}


def _days_left(now, deleted_at, retention: int) -> int:
    """Дней до окончательной очистки, с округлением вверх.

    Только что удалённая запись при retention 30 показывает 30; в
    последний неполный день — 1; после истечения — 0 (джоба заберёт).
    """
    remaining = (deleted_at + timedelta(days=retention)) - now
    return max(math.ceil(remaining.total_seconds() / 86400), 0)


@router.post("/api/trash/{kind}/{item_id}/restore")
def restore_item(
    kind: str,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    _kind(kind)
    model = _MODELS[kind]
    row = db.get(model, item_id)
    if row is None or row.deleted_at is None:
        raise HTTPException(status_code=404, detail="Запись не найдена в корзине")
    restored = _dispatch_restore(db, kind, row.project_id, user.id, item_id)
    # Коммитим до ответа: FastAPI разматывает yield-зависимости ПОСЛЕ отправки
    # ответа, и мгновенный перезапрос списка от фронта успевал увидеть ещё
    # не закоммиченное состояние — восстановленная запись выглядела
    # пропавшей (та же гонка, что чинили в import_raw почты).
    db.commit()
    with log_scope("trash", "restore", user_id=user.id):
        logger.info("trash restored kind={} id={}", kind, item_id)
    return {"kind": kind, "item": restored}


@router.delete("/api/trash/{kind}/{item_id}", status_code=204)
def purge_item(
    kind: str,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    _kind(kind)
    model = _MODELS[kind]
    row = db.get(model, item_id)
    if row is None or row.deleted_at is None:
        raise HTTPException(status_code=404, detail="Запись не найдена в корзине")
    project_id = row.project_id
    _dispatch_purge(db, kind, project_id, user.id, item_id)
    # Коммит до ответа — см. restore_item: перезапрос корзины не должен
    # видеть ещё не закоммиченное удаление.
    db.commit()
    with log_scope("trash", "purge", user_id=user.id):
        logger.info("trash purged kind={} id={}", kind, item_id)


@router.delete("/api/trash")
def purge_all(db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    """Очистить корзину целиком (патч P): все типы, окончательно.

    Идёт теми же сервисами, что и одиночное удаление — события, счётчики
    проектов и логи остаются консистентными. Потолок 2000 на тип — защита
    от случайно огромной корзины; остаток дочистит фоновая джоба.
    """
    removed = 0
    for kind in _KINDS:
        if not registry.is_enabled(kind):
            continue
        model = _MODELS[kind]
        rows = list(
            db.scalars(select(model).where(model.deleted_at.is_not(None)).limit(2000)).all()
        )
        for row in rows:
            _dispatch_purge(db, kind, row.project_id, user.id, row.id)
            removed += 1
    # Коммит до ответа — см. restore_item: счётчик корзины и повторный
    # запрос списка должны видеть уже очищенную корзину.
    db.commit()
    with log_scope("trash", "purge-all", user_id=user.id):
        logger.info("trash purged all count={}", removed)
    return {"purged": removed}


def _dispatch_restore(session: Session, kind: str, project_id: int, user_id: int, item_id: int) -> dict:
    if kind == "tasks":
        from app.modules.tasks.service import board

        return board.restore_task(session, project_id, user_id, item_id)
    if kind == "documents":
        from app.modules.documents import service

        return service.restore_document(session, project_id, user_id, item_id)
    if kind == "secrets":
        from app.modules.secrets import service

        return service.restore_secret(session, project_id, user_id, item_id)
    from app.modules.rdp import service

    return service.restore_connection(session, project_id, user_id, item_id)


def _dispatch_purge(session: Session, kind: str, project_id: int, user_id: int, item_id: int) -> None:
    if kind == "tasks":
        from app.modules.tasks.service import board

        board.purge_task(session, project_id, user_id, item_id)
    elif kind == "documents":
        from app.modules.documents import service

        service.purge_document(session, project_id, user_id, item_id)
    elif kind == "secrets":
        from app.modules.secrets import service

        service.purge_secret(session, project_id, user_id, item_id)
    else:
        from app.modules.rdp import service

        service.purge_connection(session, project_id, user_id, item_id)


def purge_expired() -> None:
    """Джоба планировщика: окончательно убирает то, что лежит дольше retention."""
    days = get_int("trash", "retention_days")
    cutoff = utcnow() - timedelta(days=days)
    removed = 0
    with session_scope() as session:
        for kind in _KINDS:
            if not registry.is_enabled(kind):
                continue
            model = _MODELS[kind]
            rows = list(
                session.scalars(
                    select(model).where(model.deleted_at.is_not(None), model.deleted_at < cutoff).limit(500)
                ).all()
            )
            for row in rows:
                _dispatch_purge(session, kind, row.project_id, None, row.id)
                removed += 1
    if removed:
        with log_scope("trash", "job"):
            logger.info("trash purged expired count={}", removed)


def setup(app) -> None:
    register_defs(DEFS)
    register_global_counters("trash", global_counts)
    register_job(
        "trash.purge",
        purge_expired,
        module="trash",
        action="purge",
        interval_module="trash",
        interval_key="purge.interval_seconds",
        label="Очистка корзины",
        detail="Удаление записей старше retention-дней",
    )
    app.include_router(router)
