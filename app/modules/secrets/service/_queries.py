"""Приватные выборки секретов и снимков истории: строка по id с проверками."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.secrets.models import Secret, SecretRevision


def _row(session: Session, project_id: int, secret_id: int, in_trash: bool = False) -> Secret:
    row = session.get(Secret, secret_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Секрет не найден")
    if in_trash and row.deleted_at is None:
        raise HTTPException(status_code=404, detail="Секрет не в корзине")
    if not in_trash and row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Секрет удалён в корзину")
    return row


def _revision_row(session: Session, secret_id: int, revision_id: int) -> SecretRevision:
    row = session.get(SecretRevision, revision_id)
    if row is None or row.secret_id != secret_id:
        raise HTTPException(status_code=404, detail="Версия секрета не найдена")
    return row
