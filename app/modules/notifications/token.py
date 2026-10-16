"""Токен BotFather: число, двоеточие и длинный ключ. Иначе Telegram отвечает Not Found."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")


def normalize_bot_token(raw: str) -> str:
    text = "".join((raw or "").split())
    folded = text.lower()
    marker = folded.find("/bot")
    if marker >= 0:
        text = text[marker + 4 :].split("/", 1)[0]
    elif folded.startswith("bot") and ":" in text[3:]:
        text = text[3:]
    return text if _TOKEN.fullmatch(text) else ""


def token_problem(raw: str) -> str:
    if not (raw or "").strip():
        return "Не задан токен бота"
    if normalize_bot_token(raw):
        return ""
    length = len("".join(raw.split()))
    return (
        "Сохранённый токен не похож на токен BotFather, в нём "
        + str(length)
        + " символов. Нужен токен целиком: число, двоеточие и длинный ключ. "
        + "Telegram на такой токен отвечает Not Found. Поле могло заполниться паролем браузера."
    )
