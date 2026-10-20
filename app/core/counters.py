"""Хаб счётчиков с кешом (патч T; провайдер-реестр — патч AA).

Одна точка, где живут числа для бейджей интерфейса: непрочитанные письма
и уведомления, корзина, секреты — глобально; документы, примеры, секреты,
RDP, письма и заметки — по проекту. Раньше эти числа считались вразнобой:
SSE-канал сам по себе, колокольчик — своим опросом, карточка проекта —
третьим путём. Теперь источник один.

Кто что считает — решают сами модули: ядро хранит только реестр
провайдеров (``register_global_counters`` / ``register_project_counters``), регистрация
идёт в ``setup()`` роутера модуля. Ядро не импортирует модели модулей,
модули не знают друг о друге — добавить числа нового раздела значит
написать один GROUP BY и одну строчку регистрации.

Как это экономит запросы (не плодим их с каждой новой фичей):

- в процессе живёт кеш с TTL (``core.counters.ttl_seconds``, по умолчанию
  15 секунд): сколько бы вкладок ни спрашивало ``/api/counters``, к базе
  идёт один запрос на окно, остальные читают кеш;
- проектные провайдеры считают GROUP BY по всем проектам сразу — один
  запрос на модуль, а не по запросу на каждый таб;
- каждая мутация сбрасывает кеш сама: проектные изменения проходят через
  ``touch_project()``, письма и уведомления публикуют сигналы шины — рядом
  стоит ``counters.invalidate()``. Числа не висят устаревшими после
  действий пользователя, TTL страхует только от правок мимо API;
- SSE-канал после сигнала шины пересчитывает принудительно (force=True)
  и записывает результат в кеш: открытые вкладки получают свежие числа
  сразу, а HTTP-запросы следом читают уже готовое.

Упавший провайдер не роняет остальные: каждый блок считается в своём
try/except — не посчиталось, поля просто нет.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends

from app.core import db as db_module
from app.core.auth import require_user
from app.core.events_bus import publish as _bus_publish
from app.core.logging import logger
from app.core.models import User

router = APIRouter()

_lock = threading.Lock()
# Реестр: имя модуля -> провайдер. Глобальный: fn(session, user_id) -> dict
# (плоские числа). Проектный: fn(session) -> dict[project_id, dict].
_global_providers: dict[str, object] = {}
_project_providers: dict[str, object] = {}

# user_id -> (monotonic-метка, снимок)
_user_cache: dict[int, tuple[float, dict]] = {}
# Общий снимок всех проектов: (monotonic-метка, {project_id: {поля}}).
# Проектные числа считаются GROUP BY по всем проектам сразу, поэтому
# и кеш один на все: пересчёт любого проекта стоит столько же.
_projects_cache: tuple[float, dict[int, dict]] | None = None


def register_global_counters(module: str, handler) -> None:
    """Зарегистрировать глобальный провайдер: ``fn(session, user_id) -> dict``."""
    _global_providers[module] = handler


def register_project_counters(module: str, handler) -> None:
    """Зарегистрировать проектный провайдер: ``fn(session) -> dict[pid, dict]``."""
    _project_providers[module] = handler


def ttl_seconds() -> float:
    from app.core.settings_store import get_int

    value = get_int("core", "counters.ttl_seconds")
    return float(value) if value and value > 0 else 15.0


def invalidate(project_id: int | None = None) -> None:
    """Сброс кеша. Вызывается из точек мутаций.

    ``project_id`` здесь для смысла, а не для адресности: проектные
    мутации меняют и глобальные числа (корзина, секреты), а проектный
    снимок общий — GROUP BY по всем проектам. Так что сбрасывается всё;
    пересчёт дешёвый, а свежесть гарантирована.

    Заодно — тихий сигнал шины ``counters.changed``: открытые SSE-каналы
    пересчитают глобальные числа сами (тип наружу не пересылается, он
    только будит генератор — как heartbeat, но сразу после действия).
    """
    global _projects_cache
    with _lock:
        _user_cache.clear()
        _projects_cache = None
    _bus_publish("counters.changed")


def user_state(user_id: int, force: bool = False) -> dict:
    """Глобальные числа для пользователя: почта, уведомления, корзина, секреты.

    ``force=True`` — пересчитать мимо кеша (SSE после сигнала шины) и
    записать результат в кеш.
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
    global _projects_cache
    now = time.monotonic()
    with _lock:
        hit = _projects_cache
    if not force and hit is not None and now - hit[0] < ttl_seconds():
        return hit[1].get(project_id, {})
    snapshot = _compute_projects()
    with _lock:
        _projects_cache = (time.monotonic(), snapshot)
    return snapshot.get(project_id, {})


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
    for module, handler in list(_global_providers.items()):
        try:
            with db_module.SessionLocal() as session:
                piece = handler(session, user_id) or {}
        except Exception:
            logger.opt(exception=True).warning("counters provider failed module={}", module)
            continue
        if isinstance(piece, dict):
            state.update(piece)
    return state


def _compute_projects() -> dict[int, dict]:
    merged: dict[int, dict] = {}
    for module, handler in list(_project_providers.items()):
        try:
            with db_module.SessionLocal() as session:
                counts = handler(session) or {}
        except Exception:
            logger.opt(exception=True).warning("counters project provider failed module={}", module)
            continue
        if not isinstance(counts, dict):
            continue
        for project_id, fields in counts.items():
            if isinstance(fields, dict):
                merged.setdefault(int(project_id), {}).update(fields)
    return merged
