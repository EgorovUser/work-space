"""Миграции схемы почты: доколонки через PRAGMA (самописный ensure_schema)."""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import session_scope


def ensure_schema() -> None:
    with session_scope() as session:
        rows = session.execute(text("PRAGMA table_info(mail_messages)")).all()
        names = {row[1] for row in rows}
        if "attachments_json" not in names:
            session.execute(text("ALTER TABLE mail_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''"))
        if "html_body" not in names:
            session.execute(text("ALTER TABLE mail_messages ADD COLUMN html_body TEXT NOT NULL DEFAULT ''"))
        accounts = session.execute(text("PRAGMA table_info(mail_accounts)")).all()
        account_names = {row[1] for row in accounts}
        if "backfill_uid" not in account_names:
            session.execute(text("ALTER TABLE mail_accounts ADD COLUMN backfill_uid INTEGER NOT NULL DEFAULT 0"))
        if "auth_blocked" not in account_names:
            session.execute(text("ALTER TABLE mail_accounts ADD COLUMN auth_blocked INTEGER NOT NULL DEFAULT 0"))
        if "auth_notified" not in account_names:
            session.execute(text("ALTER TABLE mail_accounts ADD COLUMN auth_notified INTEGER NOT NULL DEFAULT 0"))
        event_rows = session.execute(text("PRAGMA table_info(mail_events)")).all()
        event_names = {row[1] for row in event_rows}
        if event_rows and "reminded_soon" not in event_names:
            session.execute(text("ALTER TABLE mail_events ADD COLUMN reminded_soon INTEGER NOT NULL DEFAULT 0"))
        if event_rows and "reminded_day" not in event_names:
            session.execute(text("ALTER TABLE mail_events ADD COLUMN reminded_day TEXT NOT NULL DEFAULT ''"))
