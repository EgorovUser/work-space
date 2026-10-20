"""Полнотекстовый индекс поиска (FTS5).

Создаёт виртуальные таблицы fts_* и триггеры синхронизации, наполняет индекс
существующими строками. Идемпотентно: ensure_search_index() можно вызывать
сколько угодно раз (IF NOT EXISTS + наполнение только пустого индекса).

Свежие базы штампуются в head и миграцию не проходят — для них индекс
поднимается тем же ensure_search_index() прямо из init_db.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.core.search import ensure_search_index

    ensure_search_index(op.get_bind())


def downgrade() -> None:
    from app.core.search import SOURCES

    conn = op.get_bind()
    for spec in reversed(SOURCES):
        fts = spec["fts"]
        for suffix in ("_ai", "_au", "_ad"):
            conn.exec_driver_sql(f"DROP TRIGGER IF EXISTS {fts}{suffix}")
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{fts}"')
