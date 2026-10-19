from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TZDateTime, utcnow


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class ProjectNote(Base):
    __tablename__ = "project_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
