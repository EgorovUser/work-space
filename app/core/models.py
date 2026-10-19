from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TZDateTime, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_due", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class StoredFile(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class FileLink(Base):
    __tablename__ = "file_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    module: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class StatusAlert(Base):
    """Последняя поломка, о которой уже написали. Одна строка."""

    __tablename__ = "status_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text, default="")
    pending: Mapped[str] = mapped_column(Text, default="")
    notified_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class SettingDefinitionRow(Base):
    __tablename__ = "setting_definitions"

    module: Mapped[str] = mapped_column(String(50), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_type: Mapped[str] = mapped_column(String(20))
    default_json: Mapped[str] = mapped_column(Text)
    allowed_scopes: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    ui_hint: Mapped[str] = mapped_column(String(30))
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    restart_required: Mapped[bool] = mapped_column(Boolean, default=False)
    min_value: Mapped[float | None] = mapped_column(nullable=True)
    max_value: Mapped[float | None] = mapped_column(nullable=True)


class SettingValue(Base):
    __tablename__ = "setting_values"
    __table_args__ = (UniqueConstraint("module", "key", "scope_key", name="uq_setting_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module: Mapped[str] = mapped_column(String(50), index=True)
    key: Mapped[str] = mapped_column(String(100))
    scope_key: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(20))
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
