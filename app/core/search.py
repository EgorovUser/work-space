"""Полнотекстовый поиск по содержимому: задачи, заметки, письма, документы, примеры, заголовки секретов и RDP-подключения.

Индекс — отдельные FTS5-таблицы (собственное хранилище), синхронизируются
триггерами INSERT/UPDATE/DELETE у каждой таблицы-источника. Секреты
индексируются только по открытым полям (title, kind): зашифрованные
username/url/note/secret в индекс не попадают никогда. RDP-подключения
индексируются целиком (name, host, username, domain, note) — пароля там
нет по построению.

Свежая база штампуется в head, и миграции на ней не проигрываются, поэтому
ensure_search_index() вызывается из init_db всегда (идемпотентно), а
миграция 0005 — обёртка для баз, которые проходят через upgrade().
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core import registry
from app.core.auth import require_user
from app.core.db import session_scope
from app.core.logging import logger, log_scope
from app.core.models import User

# Маркеры совпадения в сниппете: невидимые управляющие символы, которые
# фронтенд превращает в <mark> (без v-html — без XSS).
SNIP_MARK = "\x01"
SNIP_END = "\x02"
SNIP_GAP = " … "

router = APIRouter()


SOURCES = (
    {
        "id": "tasks",
        "label": "Задачи",
        "table": "tasks",
        "soft_delete": True,
        "fts": "fts_tasks",
        "module": "tasks",
        "columns": ("title", "description"),
        "title": "t.title",
        "archived": False,
    },
    {
        "id": "notes",
        "label": "Заметки",
        "table": "project_notes",
        "fts": "fts_notes",
        "module": "projects",
        "columns": ("body",),
        "title": "t.body",
        "archived": False,
    },
    {
        "id": "mail",
        "label": "Письма",
        "table": "mail_messages",
        "fts": "fts_mail",
        "module": "mail",
        "columns": ("subject", "from_name", "from_addr", "body"),
        "title": "NULLIF(t.subject, '')",
        "archived": True,
    },
    {
        "id": "documents",
        "label": "Документы",
        "table": "documents",
        "soft_delete": True,
        "fts": "fts_documents",
        "module": "documents",
        "columns": ("title", "note"),
        "title": "t.title",
        "archived": True,
    },
    {
        "id": "examples",
        "label": "Примеры",
        "table": "examples",
        "fts": "fts_examples",
        "module": "examples",
        "columns": ("title", "body", "note"),
        "title": "t.title",
        "archived": True,
    },
    {
        # Только открытые поля: зашифрованное содержимое в индекс не попадает.
        "id": "secrets",
        "label": "Секреты",
        "table": "secrets",
        "soft_delete": True,
        "fts": "fts_secrets",
        "module": "secrets",
        "columns": ("title", "kind"),
        "title": "t.title",
        "archived": True,
    },
    {
        # Путь «А»: пароля в записи нет, поэтому индексируем всё — адрес
        # сервера ищется в общем поиске, как название задачи.
        "id": "rdp",
        "label": "RDP",
        "table": "rdp_connections",
        "soft_delete": True,
        "fts": "fts_rdp",
        "module": "rdp",
        "columns": ("name", "host", "username", "domain", "note"),
        "title": "t.name",
        "archived": True,
    },
)


def _match_expression(query: str) -> str | None:
    """Строит безопасное FTS5-выражение из пользовательского ввода.

    Каждое слово оборачивается в кавычки (внутренние удваиваются) и получает
    префиксную звёздочку: «проект» найдёт и «проекты». Кавычки гарантируют,
    что управляющий синтаксис FTS5 (AND/OR/скобки) в запросе не сработает.
    """
    terms = [t for t in re.split(r"\s+", (query or "").strip()) if t][:8]
    if not terms:
        return None
    return " ".join('"' + term.replace('"', '""') + '"*' for term in terms)


def ensure_search_index(conn) -> bool:
    """Создаёт FTS5-таблицы, триггеры и наполняет индекс. Идемпотентно.

    Возвращает False, если SQLite собран без FTS5 — приложение продолжает
    работать, поиск просто возвращает пустые группы.
    """
    try:
        conn.exec_driver_sql('CREATE VIRTUAL TABLE IF NOT EXISTS fts_search_probe USING fts5(x)')
        conn.exec_driver_sql("DROP TABLE IF EXISTS fts_search_probe")
    except Exception:
        with log_scope("core", "search.init"):
            logger.warning("SQLite без FTS5 — полнотекстовый поиск недоступен")
        return False

    for spec in SOURCES:
        _create_source_index(conn, spec)
    return True


def _create_source_index(conn, spec: dict) -> None:
    fts = spec["fts"]
    source = spec["table"]
    columns = spec["columns"]
    col_list = ", ".join(f'"{name}"' for name in columns)
    new_values = ", ".join(f'new."{name}"' for name in columns)

    conn.exec_driver_sql(f'CREATE VIRTUAL TABLE IF NOT EXISTS "{fts}" USING fts5({col_list})')
    conn.exec_driver_sql(
        f'CREATE TRIGGER IF NOT EXISTS {fts}_ai AFTER INSERT ON "{source}" BEGIN '
        f'INSERT INTO "{fts}"(rowid, {col_list}) VALUES (new.id, {new_values}); END'
    )
    conn.exec_driver_sql(
        f'CREATE TRIGGER IF NOT EXISTS {fts}_au AFTER UPDATE ON "{source}" BEGIN '
        f'DELETE FROM "{fts}" WHERE rowid = old.id; '
        f'INSERT INTO "{fts}"(rowid, {col_list}) VALUES (new.id, {new_values}); END'
    )
    conn.exec_driver_sql(
        f'CREATE TRIGGER IF NOT EXISTS {fts}_ad AFTER DELETE ON "{source}" BEGIN '
        f'DELETE FROM "{fts}" WHERE rowid = old.id; END'
    )

    # Первичное наполнение: индекс пуст, а источник нет (база старше индекса).
    indexed = conn.exec_driver_sql(f'SELECT count(*) FROM "{fts}"').scalar()
    if not indexed:
        total = conn.exec_driver_sql(f'SELECT count(*) FROM "{source}"').scalar()
        if total:
            conn.exec_driver_sql(
                f'INSERT INTO "{fts}"(rowid, {col_list}) SELECT id, {col_list} FROM "{source}"'
            )


def _search_source(session, spec: dict, match: str, limit: int) -> list[dict]:
    fts = spec["fts"]
    columns = spec["columns"]

    # Сниппет просим у каждой колонки и берём первую, где есть совпадение.
    snippet_exprs = ", ".join(
        f"snippet({fts}, {index}, '{SNIP_MARK}', '{SNIP_END}', '{SNIP_GAP}', 12) AS snip_{index}"
        for index in range(len(columns))
    )
    archived_expr = "t.archived" if spec["archived"] else "0"
    # Мягко удалённые записи (патч N) из поиска исчезают: у источников
    # с колонкой deleted_at добавляем фильтр, остальные её не имеют.
    deleted_expr = "t.deleted_at IS NULL" if spec.get("soft_delete") else "1"

    sql = text(
        f'SELECT f.rowid AS id, t.project_id, {spec["title"]} AS title, '
        f'{archived_expr} AS archived, {snippet_exprs} '
        f'FROM "{fts}" f JOIN "{spec["table"]}" t ON t.id = f.rowid '
        f'WHERE "{fts}" MATCH :match AND {deleted_expr} '
        f'ORDER BY bm25("{fts}") '
        f"LIMIT :limit"
    )
    rows = session.execute(sql, {"match": match, "limit": limit}).mappings().all()

    items: list[dict] = []
    for row in rows:
        snippet = ""
        for index in range(len(columns)):
            candidate = row[f"snip_{index}"] or ""
            if SNIP_MARK in candidate:
                snippet = candidate.strip()
                break
        title = row["title"]
        if title is None:
            title = "(без заголовка)"
        title = str(title).strip()
        if spec["id"] == "notes":
            title = title[:80] + ("…" if len(title) > 80 else "")
        items.append(
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "title": title,
                "snippet": snippet,
                "archived": bool(row["archived"]),
            }
        )
    return items


@router.get("/api/search")
def search(q: str = "", limit: int = 5, types: str = "", user: User = Depends(require_user)) -> dict:
    """Глобальный поиск по содержимому. Слова объединяются как AND,
    каждое ищется с префиксом («проект» найдёт «проекты»).

    types — список источников через запятую (tasks,mail,...): фильтр
    командной палитры. Пустая строка — все источники.
    """
    match = _match_expression(q)
    wanted = {part.strip() for part in types.split(",") if part.strip()}
    known = {spec["id"] for spec in SOURCES}
    wanted &= known
    groups: list[dict] = []
    if match and 1 <= limit <= 20:
        with session_scope() as session:
            for spec in SOURCES:
                if wanted and spec["id"] not in wanted:
                    continue
                if not registry.is_enabled(spec["module"]):
                    continue
                try:
                    items = _search_source(session, spec, match, limit)
                except Exception:
                    # Один сломанный источник не роняет весь поиск.
                    with log_scope("core", "search.query"):
                        logger.exception("поиск по источнику упал table={}", spec["table"])
                    continue
                if items:
                    groups.append({"id": spec["id"], "label": spec["label"], "items": items})
    return {"query": q, "groups": groups}
