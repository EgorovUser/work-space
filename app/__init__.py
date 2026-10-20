# Рабочее пространство.

# Свежий SQLite поверх системного (патч Y).
#
# Системный sqlite3 приходит из дистрибутива и бывает старым: в образе
# python:3.12-slim (Debian bookworm) это 3.40.1. У старых SQLite есть
# известные баги FTS5: после удалений integrity-проверки ложно ругаются
# «malformed inverted index», из-за чего статус «сам ломался и сам чинился».
# Починено в SQLite 3.44+.
#
# Если установлен pysqlite3-binary (requirements.txt), подменяем им
# stdlib sqlite3 ДО любых импортов SQLAlchemy: его sqlite-диалект в
# момент создания движка импортирует sqlite3 и получает свежую версию.
# Пакета нет (локальная разработка, Windows) — работаем на системном,
# страховкой остаётся авточинка индексов в core/db.py.

from __future__ import annotations

import sys

try:  # pragma: no cover — зависит от окружения, не от кода
    import pysqlite3

    import sqlite3 as _stdlib_sqlite3

    if tuple(int(p) for p in pysqlite3.sqlite_version.split(".")[:2]) > tuple(
        int(p) for p in _stdlib_sqlite3.sqlite_version.split(".")[:2]
    ):
        sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except Exception:  # noqa: BLE001 — подмена опциональна, любой сбой = системный sqlite
    pass
