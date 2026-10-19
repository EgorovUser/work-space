"""Add users.session_version for auth session invalidation.

Старые базы (образ до e59905f) не имеют колонки — seed() падал с
"no such column: users.session_version". Колонка nullable=False с
server_default=1, чтобы существующие пользователи получили валидную
версию сессий.

Идемпотентно: если колонка уже есть (образ собран между e59905f и
интеграцией alembic), миграция пропускается.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _users_columns() -> set:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns("users")}


def upgrade() -> None:
    if "session_version" in _users_columns():
        return
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    if "session_version" in _users_columns():
        op.drop_column("users", "session_version")
