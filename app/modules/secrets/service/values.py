"""Шифрование и расшифровка значений секрета: обёртки с честными ошибками."""

from __future__ import annotations

from fastapi import HTTPException

from app.core.logging import logger
from app.modules.secrets import crypto


def _pack(text: str) -> str:
    try:
        return crypto.encrypt(text)
    except Exception as exc:
        logger.warning("secret encrypt failed")
        raise HTTPException(status_code=500, detail="Не удалось сохранить секрет") from exc


def _unpack(token: str, secret_id: int) -> str:
    try:
        return crypto.decrypt(token)
    except ValueError:
        logger.warning("secret decrypt failed id={}", secret_id)
        raise HTTPException(status_code=500, detail="Не удалось прочитать секрет")


def _soft_decrypt(token: str) -> str | None:
    if not token:
        return ""
    try:
        return crypto.decrypt(token)
    except Exception:
        return None
