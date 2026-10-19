"""Unique index on (account_id, folder, uid) and index on received_at.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Удаляем дубликаты, оставляя минимальный id
    op.execute("""
        DELETE FROM mail_messages
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM mail_messages
            WHERE account_id IS NOT NULL AND uid IS NOT NULL
            GROUP BY account_id, folder, uid
        )
        AND account_id IS NOT NULL AND uid IS NOT NULL
    """)

    # Уникальный индекс (только для не-нуллевых account_id/uid)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mail_messages_account_folder_uid
        ON mail_messages (account_id, folder, uid)
        WHERE account_id IS NOT NULL AND uid IS NOT NULL
    """)

    # Индекс для сортировки по дате
    op.create_index(
        "ix_mail_messages_received_at",
        "mail_messages",
        ["received_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_mail_messages_received_at", table_name="mail_messages")
    op.execute("DROP INDEX IF EXISTS uq_mail_messages_account_folder_uid")
