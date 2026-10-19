"""Один Fernet на процесс. Им пользуются настройки, секреты и пароль почты."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get as get_config


def fernet() -> Fernet:
    return Fernet(get_config().fernet_key.encode("ascii"))


def encrypt(text: str) -> str:
    if text == "":
        return ""
    return fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str, failed: str = "не удалось прочитать значение") -> str:
    if not token:
        return ""
    try:
        return fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError(failed) from exc
