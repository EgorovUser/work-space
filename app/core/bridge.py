"""Точки стыка модулей. Чужие таблицы отсюда не читаются."""

from __future__ import annotations

from app.core.logging import logger

CARD_FIELDS = {
    "tasks": ("open_tasks", "overdue_tasks", "nearest_deadline"),
    "timetracking": ("hours_week",),
    "mail": ("new_mail",),
}

SEARCH_MODULES = ("tasks", "documents", "examples", "mail", "secrets")

_project_created: list = []
_card: dict = {}
_dashboard: dict = {}
_search: dict = {}
_inbox: dict = {}
_materialize: dict = {}
_home_blocks: dict = {}


def on_project_created(handler) -> None:
    _project_created.append(handler)


def register_card(module: str, handler) -> None:
    _card[module] = handler


def register_dashboard(module: str, handler) -> None:
    _dashboard[module] = handler


def register_search(module: str, handler) -> None:
    _search[module] = handler


def register_inbox(module: str, handler) -> None:
    _inbox[module] = handler


def register_home_block(name: str, handler) -> None:
    """Блок для хаба «Сегодня»: модуль отдаёт ленту без проектного охвата.

    В отличие от inbox, блок главной привязан к пользователю, а не к списку
    проектов — уведомления не делятся по проектам. Лимит блок читает из
    собственных настроек модуля.
    """
    _home_blocks[name] = handler


def home_block(name: str, session, user_id: int | None) -> list:
    handler = _home_blocks.get(name)
    if handler is None:
        return []
    try:
        return list(handler(session, user_id) or [])
    except Exception:
        logger.exception("home block failed name={}", name)
        return []


def register_materialize(kind: str, handler) -> None:
    _materialize[kind] = handler


def materialize(kind: str, session, project_id: int, user_id: int, upload) -> dict:
    handler = _materialize.get(kind)
    if handler is None:
        raise RuntimeError("Некуда сохранить файл: " + kind)
    return handler(session, project_id, user_id, upload)


def run_project_created(session, project) -> None:
    for handler in list(_project_created):
        handler(session, project)


def card_summary(session, project_id: int, user_id: int | None) -> dict:
    result = {field: None for fields in CARD_FIELDS.values() for field in fields}
    for module, fields in CARD_FIELDS.items():
        handler = _card.get(module)
        if handler is None:
            continue
        try:
            piece = handler(session, project_id, user_id) or {}
        except Exception:
            logger.exception("card provider failed module={}", module)
            continue
        for field in fields:
            if field in piece:
                result[field] = piece[field]
    return result


def dashboard_blocks(session, project_id: int, user_id: int | None, limits: dict) -> dict:
    merged: dict = {}
    for module, handler in list(_dashboard.items()):
        try:
            piece = handler(session, project_id, user_id, limits) or {}
        except Exception:
            logger.exception("dashboard provider failed module={}", module)
            continue
        if isinstance(piece, dict):
            merged.update(piece)
    return merged


def inbox_items(module: str, session, user_id: int | None, limit: int, project_ids: list[int]) -> list:
    handler = _inbox.get(module)
    if handler is None or not project_ids:
        return []
    try:
        rows = handler(session, user_id, limit, project_ids) or []
    except Exception:
        logger.exception("inbox provider failed module={}", module)
        return []
    return list(rows)


def search_groups(session, project_id: int, user_id: int | None, query: str, limit: int) -> dict:
    groups = {}
    for module in SEARCH_MODULES:
        handler = _search.get(module)
        if handler is None:
            groups[module] = None
            continue
        try:
            groups[module] = handler(session, project_id, user_id, query, limit)
        except Exception:
            logger.exception("search provider failed module={}", module)
            groups[module] = None
    return groups
