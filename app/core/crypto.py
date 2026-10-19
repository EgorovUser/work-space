"""MultiFernet: шифрование текущим ключом, расшифровка любым из списка.

FERNET_KEY — текущий (им шифруем).
FERNET_KEY_OLD — опциональный старый (только для расшифровки).
При следующем сохранении записи перешифровываются текущим ключом.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get as get_config


def _keys() -> list[Fernet]:
    cfg = get_config()
    keys = [Fernet(cfg.fernet_key.encode("ascii"))]
    old = getattr(cfg, "fernet_key_old", "") or ""
    if old:
        keys.append(Fernet(old.encode("ascii")))
    return keys


def multi() -> MultiFernet:
    return MultiFernet(_keys())


def encrypt(text: str) -> str:
    if text == "":
        return ""
    return multi().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str, failed: str = "не удалось прочитать значение") -> str:
    if not token:
        return ""
    try:
        return multi().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError(failed) from exc
