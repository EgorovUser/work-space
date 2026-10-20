"""Хаб счётчиков с кэшем (патч T).

Одна точка, где живут числа для бейджей интерфейса: непрочитанные письма
и уведомления, корзина, секреты — глобально; документы, примеры, секреты,
RDP, письма и заметки — по проекту. Раньше эти числа считались вразнобой:
SSE-канал сам по себе, колокольчик — своим опросом, карточка проекта —
третьим путём. Теперь источник один.

Как это экономит запросы (не плодим их с каждой новой фичей):

- в процессе живёт кэш с TTL (``core.counters.ttl_seconds``, по умолчанию
  15 секунд): сколько бы вкладок ни спрашивало ``/api/counters``, к базе
  идёт один запрос на окно, остальные читают кэш;
- каждая мутация сбрасывает кэш сама: проектные изменения проходят через
  ``touch_project()``, письма и уведомления публикуют сигналы шины — рядом
  стоит ``counters.invalidate()``. Числа не висят устаревшими после
  действий пользователя, TTL страхует только от правок мимо API;
- SSE-канал после сигнала шины пересчитывает принудительно (force=True)
  и записывает результат в кэш: открытые вкладки получают свежие числа
  сразу, а HTTP-запросы следом читают уже готовое.

Упавший модуль не роняет остальные: как и в SSE, каждый блок считается
в своём try/except — не посчиталось, поля просто нет.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.core import db as db_module
from app.core.auth import require_user
from app.core.logging import logger
from app.core.models import User

router = APIRouter()

_lock = threading.Lock()
# user_id / project_id -> (monotonic-метка, снимок)
_user_cache: dict[int, tuple[float, dict]] = {}
_project_cache: dict[int, tuple[float, dict]] = {}


def ttl_seconds() -> float:
    from app.core.settings_store import get_int

    value = get_int("core", "counters.ttl_seconds")
    return float(value) if value and value > 0 else 15.0


def invalidate(project_id: int | None = None) -> None:
    """Сброс кэша. Вызывается из точек мутаций.

    ``project_id=None`` — всё; конкретный проект — его счётчики плюс
    глобальные (корзина и секреты меняются проектными мутациями, поэтому
    пользовательский кэш сбрасывается целиком).
    """
    with _lock:
        if project_id is None:
            _user_cache.clear()
            _project_cache.clear()
        else:
            _project_cache.pop(project_id, None)
            _user_cache.clear()


def user_state(user_id: int, force: bool = False) -> dict:
    """Глобальные числа для пользователя: почта, уведомления, корзина, секреты.

    ``force=True`` — пересчитать мимо кэша (SSE после сигнала шины) и
    записать результат в кэш.
    """
    now = time.monotonic()
    with _lock:
        hit = _user_cache.get(user_id)
    if not force and hit is not None and now - hit[0] < ttl_seconds():
        return hit[1]
    state = _compute_user_state(user_id)
    with _lock:
        _user_cache[user_id] = (time.monotonic(), state)
    return state


def project_counts(project_id: int, force: bool = False) -> dict:
    """Числа одного проекта: документы, примеры, секреты, RDP, письма, заметки.

    Считается то, что показывают списки разделов по умолчанию: активное
    (не в архиве, не в корзине). «Почта» — непрочитанные, подходящие под
    правила проекта, как в карточке проекта.
    """
    now = time.monotonic()
    with _lock:
        hit = _project_cache.get(project_id)
    if not force and hit is not None and now - hit[0] < ttl_seconds():
        return hit[1]
    counts = _compute_project_counts(project_id)
    with _lock:
        _project_cache[project_id] = (time.monotonic(), counts)
    return counts


@router.get("/api/counters")
def counters_state(
    project_id: int | None = None,
    user: User = Depends(require_user),
) -> dict:
    """Снимок чисел для бейджей; ``?project_id=`` добавляет блок проекта."""
    payload = user_state(user.id)
    if project_id is not None:
        payload["project"] = project_counts(project_id)
    return payload


def _compute_user_state(user_id: int) -> dict:
    state: dict = {}
    try:
        from app.modules.mail.models import MailMessage

        with db_module.SessionLocal() as session:
            unread = session.scalar(
                select(func.count())
                .select_from(MailMessage)
                .where(MailMessage.read.is_(False), MailMessage.archived.is_(False))
            )
        state["mail_unread"] = int(unread or 0)
    except Exception:
        logger.opt(exception=True).warning("counters mail unread failed")
    try:
        from app.modules.notifications.models import Notification

        with db_module.SessionLocal() as session:
            unread = session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.show_browser.is_(True),
                    Notification.read.is_(False),
                )
            )
        state["notifications_unread"] = int(unread or 0)
    except Exception:
        logger.opt(exception=True).warning("counters notifications failed")
    try:
        from app.modules.documents.models import Document
        from app.modules.rdp.models import RdpConnection
        from app.modules.secrets.models import Secret
        from app.modules.tasks.models import Task

        with db_module.SessionLocal() as session:
            total = 0
            for model in (Task, Document, Secret, RdpConnection):
                total += int(
                    session.scalar(
                        select(func.count()).select_from(model).where(model.deleted_at.is_not(None))
                    )
                    or 0
                )
        state["trash_total"] = total
    except Exception:
        logger.opt(exception=True).warning("counters trash failed")
    try:
        from app.modules.secrets.models import Secret

        with db_module.SessionLocal() as session:
            active = session.scalar(
                select(func.count())
                .select_from(Secret)
                .where(Secret.archived.is_(False), Secret.deleted_at.is_(None))
            )
        state["secrets_total"] = int(active or 0)
    except Exception:
        logger.opt(exception=True).warning("counters secrets failed")
    return state


def _count(session, model, *conditions) -> int:
    return int(session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


def _compute_project_counts(project_id: int) -> dict:
    counts: dict = {}
    try:
        from app.modules.documents.models import Document
        from app.modules.examples.models import Example
        from app.modules.projects.models import ProjectNote
        from app.modules.rdp.models import RdpConnection
        from app.modules.secrets.models import Secret

        with db_module.SessionLocal() as session:
            counts["documents"] = _count(
                session,
                Document,
                Document.project_id == project_id,
                Document.archived.is_(False),
                Document.deleted_at.is_(None),
            )
            counts["examples"] = _count(
                session,
                Example,
                Example.project_id == project_id,
                Example.archived.is_(False),
            )
            counts["secrets"] = _count(
                session,
                Secret,
                Secret.project_id == project_id,
                Secret.archived.is_(False),
                Secret.deleted_at.is_(None),
            )
            counts["rdp"] = _count(
                session,
                RdpConnection,
                RdpConnection.project_id == project_id,
                RdpConnection.archived.is_(False),
                RdpConnection.deleted_at.is_(None),
            )
            counts["notes"] = _count(session, ProjectNote, ProjectNote.project_id == project_id)
    except Exception:
        logger.opt(exception=True).warning("counters project block failed")
    try:
        from app.modules.mail.service.providers import card_provider

        with db_module.SessionLocal() as session:
            counts["mail"] = int(card_provider(session, project_id, None).get("new_mail") or 0)
    except Exception:
        logger.opt(exception=True).warning("counters project mail failed")
    return counts
