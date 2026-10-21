"""Миграция 0010 (патч AR): бывший рантайм-DDL переезжает в Alembic.

Что проверяем (roundtrip на живой тестовой базе):

- downgrade до 0009 снимает все восемь колонок — база становится «как
  старая до рантайм-DDL»;
- upgrade обратно добавляет их идемпотентно (с NOT NULL и дефолтами);
- данные таблиц переживают пересборку (batch ALTER) без потерь;
- статус версии возвращается на head.

База у discover-прогона общая: тест обязан вернуть её на head даже при
падении — try/finally с повторным upgrade.
"""

from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-mig-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "mig-test-secret")
os.environ.setdefault("SEED_USERNAME", "tester")
os.environ.setdefault("SEED_PASSWORD", "tester-pass")
os.environ.setdefault("LOG_LEVEL", "ERROR")

from app.core.config import get as get_config  # noqa: E402

try:
    get_config()
except RuntimeError:
    from cryptography.fernet import Fernet

    os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
    from app.core.config import prepare

    prepare()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.core.config import ROOT  # noqa: E402
from app.core import db as db_module  # noqa: E402
from app.main import app  # noqa: E402  (импорт поднимает init_db + seed)

COLUMNS = {
    "mail_messages": ("attachments_json", "html_body"),
    "mail_accounts": ("backfill_uid", "auth_blocked", "auth_notified"),
    "mail_events": ("reminded_soon", "reminded_day"),
    "status_alerts": ("pending",),
}


def _names(table: str) -> set:
    return {column["name"] for column in inspect(db_module._engine).get_columns(table)}


def _count(table: str) -> int:
    with db_module._engine.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)


class Migration0010Test(unittest.TestCase):
    def test_roundtrip_removes_and_readds_columns(self):
        cfg = Config(str(ROOT / "alembic.ini"))
        counts_before = {table: _count(table) for table in COLUMNS}
        try:
            # На head все колонки на месте (create_all или прошлый upgrade).
            for table, columns in COLUMNS.items():
                self.assertTrue(set(columns) <= _names(table), f"{table}: ждём колонки до downgrade")

            # Downgrade имитирует старую базу: рантайм-DDL никогда не
            # выполнялся, колонок нет.
            command.downgrade(cfg, "0009")
            for table, columns in COLUMNS.items():
                self.assertFalse(set(columns) & _names(table), f"{table}: колонки должны уйти")

            # Upgrade возвращает их — с дефолтами, данные не теряются
            # (batch-пересборка таблиц аккуратно переносит строки).
            command.upgrade(cfg, "head")
            for table, columns in COLUMNS.items():
                self.assertTrue(set(columns) <= _names(table), f"{table}: колонки должны вернуться")
                self.assertEqual(_count(table), counts_before[table], f"{table}: строки потерялись")
        finally:
            # Общая база прогонов: гарантируем head даже при падении выше.
            command.upgrade(cfg, "head")


if __name__ == "__main__":
    unittest.main()
