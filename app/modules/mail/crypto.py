"""Пароль ящика. Тот же ключ, что у настроек и секретов."""

from app.core.crypto import decrypt as _decrypt
from app.core.crypto import encrypt


def decrypt(token: str) -> str:
    return _decrypt(token, "не удалось прочитать пароль")
