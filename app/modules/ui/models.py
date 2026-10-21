from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TZDateTime, utcnow


class UiConfig(Base):
    """Конфигурация редактируемой страницы одного пользователя.

    JSON под капотом — руки пользователя его никогда не касаются: пишет
    и валидирует визуальный редактор (стиль storage-режима Lovelace у
    Home Assistant). Строка одна на пару (страница, пользователь).
    """

    __tablename__ = "ui_configs"
    __table_args__ = (Index("uq_ui_configs_page_user", "page", "user_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, default="[]")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class UiConfigRevision(Base):
    """Снимок конфига страницы перед изменением (патч AW).

    По образцу ``secret_revisions``: откат не разрушающий — текущие
    значения перед откатом тоже становятся снимком. Внешнего ключа на
    ``ui_configs`` нет сознательно: «Сбросить к стандартной» удаляет
    строку конфига, а история обязана пережить сброс — «ой, откатить»
    возможно и после него.
    """

    __tablename__ = "ui_config_revisions"
    __table_args__ = (Index("ix_ui_config_revisions_page", "page", "user_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    page: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, default="[]")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
