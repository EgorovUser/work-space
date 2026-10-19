"""Clean duplicate positions on tasks and task_statuses.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Переупорядочиваем position у колонок внутри проекта
    op.execute("""
        WITH ordered AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY position, id) - 1 AS new_pos
            FROM task_statuses
        )
        UPDATE task_statuses
        SET position = (SELECT new_pos FROM ordered WHERE ordered.id = task_statuses.id)
    """)

    # Переупорядочиваем position у задач внутри (project_id, status_id)
    op.execute("""
        WITH ordered AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY project_id, status_id ORDER BY position, id) - 1 AS new_pos
            FROM tasks
        )
        UPDATE tasks
        SET position = (SELECT new_pos FROM ordered WHERE ordered.id = tasks.id)
    """)


def downgrade() -> None:
    # Обратно не восстанавливаем — это одноразовая чистка
    pass
