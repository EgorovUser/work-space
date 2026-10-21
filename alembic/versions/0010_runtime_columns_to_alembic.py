"""Patch AR: колонки, раньше добавлявшиеся рантайм-DDL, переезжают в Alembic.

До этого патча модуль почты и сторож состояния допиливали схему сами:
mail/service/schema.py (ensure_schema с семью ALTER TABLE) и ALTER в
status_check._note — при живом контракте проекта «формат базы меняется
только миграциями». Здесь все восемь колонок получают честную миграцию:
базы, уже получившие их от рантайм-DDL, проходят без изменений, базы
на 0009 без колонок — получают их, реплей с промежуточной ревизии
перестаёт зависеть от самописного ensure_schema.

Идемпотентно, как 0008: свежая база получает колонки через create_all
(models их декларируют), здесь остаётся добавить их живым базам.
FK и индексы не затрагиваем — колонки без ограничений.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


# table -> ((колонка, тип, server_default), ...)
_COLUMNS = (
    (
        "mail_messages",
        (
            ("attachments_json", sa.Text(), ""),
            ("html_body", sa.Text(), ""),
        ),
    ),
    (
        "mail_accounts",
        (
            ("backfill_uid", sa.Integer(), "0"),
            ("auth_blocked", sa.Integer(), "0"),
            ("auth_notified", sa.Integer(), "0"),
        ),
    ),
    (
        "mail_events",
        (
            ("reminded_soon", sa.Integer(), "0"),
            ("reminded_day", sa.Text(), ""),
        ),
    ),
    (
        "status_alerts",
        (
            ("pending", sa.Text(), ""),
        ),
    ),
)


def upgrade() -> None:
    tables = _tables()
    for table, columns in _COLUMNS:
        if table not in tables:
            continue
        existing = _columns(table)
        for name, kind, default in columns:
            if name not in existing:
                op.add_column(table, sa.Column(name, kind, nullable=False, server_default=default))


def downgrade() -> None:
    tables = _tables()
    for table, columns in _COLUMNS:
        if table not in tables:
            continue
        existing = _columns(table)
        for name, _kind, _default in columns:
            if name in existing:
                op.drop_column(table, name)
