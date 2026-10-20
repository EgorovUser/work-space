from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TZDateTime, utcnow


class Secret(Base):
    __tablename__ = "secrets"
    __table_args__ = (Index("ix_secrets_project", "project_id", "archived"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default="")
    username_enc: Mapped[str] = mapped_column(Text, default="")
    url_enc: Mapped[str] = mapped_column(Text, default="")
    note_enc: Mapped[str] = mapped_column(Text, default="")
    secret_enc: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Мягкое удаление (патч N): заполнено — секрет в корзине.
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
