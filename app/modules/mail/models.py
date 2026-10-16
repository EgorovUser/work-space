from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TZDateTime, utcnow


class MailAccount(Base):
    __tablename__ = "mail_accounts"
    __table_args__ = (Index("ix_mail_accounts_project", "project_id", "enabled"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[str] = mapped_column(Text, default="")
    password_enc: Mapped[str] = mapped_column(Text, default="")
    folder: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_uid: Mapped[int] = mapped_column(Integer, default=0)
    backfill_uid: Mapped[int] = mapped_column(Integer, default=0)
    auth_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    auth_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class MailRule(Base):
    __tablename__ = "mail_rules"
    __table_args__ = (Index("ix_mail_rules_project", "project_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    field: Mapped[str] = mapped_column(Text)
    op: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class MailMessage(Base):
    __tablename__ = "mail_messages"
    __table_args__ = (
        Index("ix_mail_messages_project", "project_id", "archived", "read"),
        Index("ix_mail_messages_uid", "account_id", "folder", "uid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("mail_accounts.id", ondelete="SET NULL"), nullable=True)
    uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    folder: Mapped[str] = mapped_column(Text, default="")
    rfc_message_id: Mapped[str] = mapped_column(Text, default="")
    from_name: Mapped[str] = mapped_column(Text, default="")
    from_addr: Mapped[str] = mapped_column(Text, default="")
    to_addr: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    html_body: Mapped[str] = mapped_column(Text, default="")
    attachments_json: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(TZDateTime)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class MailAttachment(Base):
    __tablename__ = "mail_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"))
    filename: Mapped[str] = mapped_column(Text, default="")


class MailFiling(Base):
    """Письмо уже отнесено к проекту, повторно в папку его не двигаем."""

    __tablename__ = "mail_filings"
    __table_args__ = (UniqueConstraint("message_id", "project_id", name="uq_mail_filing"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class MailEvent(Base):
    __tablename__ = "mail_events"
    __table_args__ = (Index("ix_mail_events_start", "starts_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True)
    ical_uid: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(TZDateTime)
    ends_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    location: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    reminded_soon: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_day: Mapped[str] = mapped_column(Text, default="")


class MailTag(Base):
    __tablename__ = "mail_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class MailTagRule(Base):
    __tablename__ = "mail_tag_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("mail_tags.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(Text)
    op: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text, default="")


class MailTagPin(Base):
    """Хештег поставлен на письмо вручную."""

    __tablename__ = "mail_tag_pins"
    __table_args__ = (UniqueConstraint("message_id", "tag_id", name="uq_mail_tag_pin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("mail_tags.id", ondelete="CASCADE"), index=True)


class MailNotifyRule(Base):
    """Условие, при котором новое письмо поднимает уведомление."""

    __tablename__ = "mail_notify_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    field: Mapped[str] = mapped_column(Text)
    op: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)


class MailTagHide(Base):
    """Автохештег скрыт с этого письма."""

    __tablename__ = "mail_tag_hides"
    __table_args__ = (UniqueConstraint("message_id", "tag_id", name="uq_mail_tag_hide"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("mail_tags.id", ondelete="CASCADE"), index=True)
