"""Patch N: rdp_connections.secret_id and soft-delete columns.

Патч N: у RDP-подключения появляется связка с секретом того же проекта
(логин подтягивается в .rdp из хранилища), а задачи, документы, секреты и
RDP-подключения получают мягкое удаление — «Корзина» с восстановлением
в течение retention-дней и джобой очистки.

Идемпотентно: свежая база уже получает колонки через create_all, здесь
остаётся добавить их старым (живым) базам. FK-ограничение для secret_id
не создаём: SQLite его на живой таблице не добавляет без пересборки,
принадлежность секрета проекту проверяет сервис.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.db import TZDateTime

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "rdp_connections" in tables and "secret_id" not in _columns("rdp_connections"):
        op.add_column("rdp_connections", sa.Column("secret_id", sa.Integer(), nullable=True))
    for table in ("tasks", "documents", "secrets", "rdp_connections"):
        if table in tables and "deleted_at" not in _columns(table):
            op.add_column(table, sa.Column("deleted_at", TZDateTime(), nullable=True))


def downgrade() -> None:
    tables = _tables()
    if "rdp_connections" in tables and "secret_id" in _columns("rdp_connections"):
        op.drop_column("rdp_connections", "secret_id")
    for table in ("tasks", "documents", "secrets", "rdp_connections"):
        if table in tables and "deleted_at" in _columns(table):
            op.drop_column(table, "deleted_at")
