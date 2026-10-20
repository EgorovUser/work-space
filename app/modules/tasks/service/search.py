"""Поиск открытых задач всех проектов — выбор «на чём сфокусироваться».

Пикер помодоро (патч AF): раньше задача выбиралась из списка дня со сроками
(до 30 штук), теперь — любая живая задача находится поиском. Совпадения
ищет тот же FTS5-индекс, что и общий поиск: слова с префиксом, регистр
не важен. Показываем только живое — не удалённое в корзину, не закрытое,
не из архива проекта.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import logger, log_scope
from app.core.search import match_expression

_LIMIT_MAX = 20


def search_tasks(session: Session, q: str, limit: int = 20) -> list[dict]:
    """Открытые задачи всех проектов по префиксному полнотекстовому запросу."""
    match = match_expression(q)
    if not match:
        return []
    sql = text(
        "SELECT f.rowid AS id, t.project_id, p.name AS project_name, "
        "t.title AS title, s.name AS status_name "
        "FROM fts_tasks f "
        "JOIN tasks t ON t.id = f.rowid "
        "JOIN projects p ON p.id = t.project_id "
        "JOIN task_statuses s ON s.id = t.status_id "
        "WHERE fts_tasks MATCH :match "
        "AND t.deleted_at IS NULL AND t.closed_at IS NULL AND s.is_closed = 0 "
        "AND p.archived = 0 "
        "ORDER BY bm25(fts_tasks) "
        "LIMIT :limit"
    )
    try:
        rows = session.execute(sql, {"match": match, "limit": limit}).mappings().all()
    except Exception:
        # Битый индекс не должен ронять выбор задачи: периодическая проверка
        # целостности починит его (патч Y), а пикер честно ответит «ничего
        # не нашлось» — это лучше, чем сломанная карточка помодоро.
        with log_scope("tasks", "search.picker"):
            logger.exception("поиск задач для помодоро упал")
        return []
    return [
        {
            "id": row["id"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "title": row["title"],
            "status_name": row["status_name"],
        }
        for row in rows
    ]


def clamp_limit(limit: int) -> int:
    return max(1, min(_LIMIT_MAX, limit))
