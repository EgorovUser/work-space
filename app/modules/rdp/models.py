from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TZDateTime, utcnow


class RdpConnection(Base):
    __tablename__ = "rdp_connections"
    __table_args__ = (Index("ix_rdp_project", "project_id", "archived"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer, default=3389)
    username: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
