"""Patch O: secret_revisions — история значений секрета для отката.

Патч O: у секрета появляется история значений. Когда обновление меняет
пароль, логин или ссылку, прежнее состояние сохраняется снимком в
`secret_revisions` (то же Fernet-шифрование, что и у самого секрета).
Из истории значение можно скопировать или вернуть кнопкой «Вернуть» —
откат не разрушающий: текущие значения перед откатом тоже становятся
снимком. Глубина истории — настройка `secrets.history.keep_revisions`.

Идемпотентно: свежая база получает таблицу через create_all, живой базе
её добавляет эта миграция.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.db import TZDateTime

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "secret_revisions" not in _tables():
        op.create_table(
            "secret_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("secret_id", sa.Integer(), sa.ForeignKey("secrets.id"), nullable=False),
            sa.Column("username_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column("url_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column("secret_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", TZDateTime(), nullable=False),
        )
        op.create_index(
            "ix_secret_revisions_secret",
            "secret_revisions",
            ["secret_id", "id"],
        )


def downgrade() -> None:
    if "secret_revisions" in _tables():
        op.drop_index("ix_secret_revisions_secret", table_name="secret_revisions")
        op.drop_table("secret_revisions")
