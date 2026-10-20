"""Приватные выборки секретов и снимков истории: строка по id с проверками."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.entities import owned_row
from app.modules.secrets.models import Secret, SecretRevision


def _row(session: Session, project_id: int, secret_id: int, in_trash: bool = False) -> Secret:
    return owned_row(
        session,
        Secret,
        project_id,
        secret_id,
        in_trash=in_trash,
        label="Секрет",
        not_found="Секрет не найден",
        deleted_to_trash="Секрет удалён в корзину",
    )


def _revision_row(session: Session, secret_id: int, revision_id: int) -> SecretRevision:
    row = session.get(SecretRevision, revision_id)
    if row is None or row.secret_id != secret_id:
        raise HTTPException(status_code=404, detail="Версия секрета не найдена")
    return row
