"""Add tasks.repeat_kind / repeat_interval / repeat_until.

Повторяющиеся задачи: правило живёт на самой задаче, следующее вхождение
создаётся в момент закрытия (см. app/modules/tasks/service/recurrence.py).
Старые базы получают пустое правило («не повторяется») через server_default.

Идемпотентно: колонки, уже добавленные create_all на свежей базе,
миграция не дублирует.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.db import TZDateTime

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("repeat_kind", "repeat_interval", "repeat_until")


def _task_columns() -> set:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns("tasks")}


def upgrade() -> None:
    have = _task_columns()
    if "repeat_kind" not in have:
        op.add_column("tasks", sa.Column("repeat_kind", sa.String(length=20), nullable=False, server_default=""))
    if "repeat_interval" not in have:
        op.add_column("tasks", sa.Column("repeat_interval", sa.Integer(), nullable=False, server_default=sa.text("1")))
    if "repeat_until" not in have:
        op.add_column("tasks", sa.Column("repeat_until", TZDateTime(), nullable=True))


def downgrade() -> None:
    have = _task_columns()
    for name in _COLUMNS:
        if name in have:
            op.drop_column("tasks", name)
