"""Patch AW: ui_configs + ui_config_revisions — визуальный редактор страниц.

Конфигурация редактируемых страниц («Сегодня» — первая) хранится JSON-ом
на пользователя: элементы и их презентационные свойства (ширина в
колонках сетки, скрытие, свой заголовок, плотность). Каждое реальное
изменение сохраняет снимок прежнего состояния в ``ui_config_revisions``
— откат не разрушающий, история переживает сброс к стандартной (внешнего
ключа на конфиг нет сознательно).

Идемпотентно: свежая база получает таблицы через create_all, живой базе
их добавляет эта миграция.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.db import TZDateTime

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "ui_configs" not in _tables():
        op.create_table(
            "ui_configs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("page", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("data_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("updated_at", TZDateTime(), nullable=False),
        )
        op.create_index(
            "uq_ui_configs_page_user",
            "ui_configs",
            ["page", "user_id"],
            unique=True,
        )
    if "ui_config_revisions" not in _tables():
        op.create_table(
            "ui_config_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("page", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("data_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", TZDateTime(), nullable=False),
        )
        op.create_index(
            "ix_ui_config_revisions_page",
            "ui_config_revisions",
            ["page", "user_id", "id"],
        )


def downgrade() -> None:
    if "ui_config_revisions" in _tables():
        op.drop_index("ix_ui_config_revisions_page", table_name="ui_config_revisions")
        op.drop_table("ui_config_revisions")
    if "ui_configs" in _tables():
        op.drop_index("uq_ui_configs_page_user", table_name="ui_configs")
        op.drop_table("ui_configs")
