"""Шифрование значений секрета. Ключ — FERNET_KEY процесса, тот же, что у настроек."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get as get_config


def encrypt(text: str) -> str:
    if text == "":
        return ""
    token = _box().encrypt(text.encode("utf-8"))
    return token.decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _box().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("не удалось прочитать секрет") from exc


def _box() -> Fernet:
    return Fernet(get_config().fernet_key.encode("ascii"))
