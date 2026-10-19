"""Initial schema (placeholder — tables created by create_all on fresh DB).

Revision ID: 0001
Revises:
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # На свежей базе таблицы создаются через Base.metadata.create_all()
    # до вызова этой ревизии. На существующей — stamp.
    pass


def downgrade() -> None:
    pass
