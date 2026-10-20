"""Create rdp_connections.

RDP-подключения (патч M): название, адрес, порт, логин, домен и заметка.
Пароль не хранится — .rdp собирается на сервере, учётные данные Windows
спрашивает сам клиент при подключении (путь «А»).

Идемпотентно: таблицу, уже созданную create_all на свежей базе, миграция
не дублирует. FTS-индекс rdp создаётся ensure_search_index() из init_db.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.db import TZDateTime

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "rdp_connections" in _tables():
        return
    op.create_table(
        "rdp_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="3389"),
        sa.Column("username", sa.Text(), nullable=False, server_default=""),
        sa.Column("domain", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", TZDateTime(), nullable=True),
        sa.Column("updated_at", TZDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_rdp_connections_project_id", "rdp_connections", ["project_id"], unique=False)
    op.create_index("ix_rdp_project", "rdp_connections", ["project_id", "archived"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_rdp_project", table_name="rdp_connections")
    op.drop_index("ix_rdp_connections_project_id", table_name="rdp_connections")
    op.drop_table("rdp_connections")
