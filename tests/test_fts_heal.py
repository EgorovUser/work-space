"""FTS5-здоровье (патч Y): ложные срабатывания quick_check и авточинка.

Что проверяем:

- жалоба quick_check «malformed inverted index» на ЖИВОЙ индекс не роняет
  healthcheck: точная проверка FTS5 проходит, строчка уходит из вердикта
  (известное поведение старых SQLite, из-за которого статус «сам чинился»);
- реально повреждённый индекс пересобирается из источника: после
  healthcheck поиск снова находит запись, статус не падает;
- жалоба не про FTS остаётся в вердикте — healthcheck честно падает;
- POST /api/system/db/reindex пересобирает все индексы и возвращает
  счётчик строк.
"""

from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-fts-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "fts-test-secret")
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

from starlette.testclient import TestClient  # noqa: E402

from app.core import db as db_module  # noqa: E402
from app.core.search import fts_integrity_ok  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

PASSWORD = "tester-pass"
MARK = "fts" + os.urandom(4).hex()


def _login() -> None:
    client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})


def _project(name: str) -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _task(project_id: int, title: str) -> dict:
    response = client.post(f"/api/projects/{project_id}/tasks", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def _break_fts_tasks() -> None:
    """Сломать инвертированный индекс задачами: правим теневую таблицу.

    Внутренности FTS5 живут в обычных таблицах fts_tasks_*; выкидывание
    строк из fts_tasks_data рассинхронизирует сегменты с данными —
    integrity-check это ловит, поиск врёт.
    """
    with db_module._engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM fts_tasks_data WHERE id % 2 = 0")


class FtsHealTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _login()
        cls.project = _project("fts-heal-" + MARK)
        cls.task = _task(cls.project["id"], "задача " + MARK + " для проверки лечения")

    def test_live_index_ignored_by_quick_check_verdict(self):
        # Живой индекс: жалоба из вердикта убирается, healthcheck не падает.
        verdict = [
            "malformed inverted index for FTS5 table main.fts_tasks",
            "row 1 missing from index fts_tasks",  # не-fts формат? нет — оставляем и это
        ]
        # «row missing from index» — не наш паттерн, потому обязана остаться.
        healed = db_module._heal_fts_verdicts(None, verdict)
        self.assertIn("row 1 missing from index fts_tasks", healed)
        self.assertNotEqual(healed, ["ok"])

    def test_false_alarm_on_healthy_index_clears_verdict(self):
        # Только fts-жалоба на живой индекс → вердикт становится ok.
        verdict = ["malformed inverted index for FTS5 table main.fts_tasks"]
        healed = db_module._heal_fts_verdicts(None, verdict)
        self.assertEqual(healed, ["ok"])

    def test_broken_index_is_rebuilt_from_source(self):
        _break_fts_tasks()
        self.assertFalse(fts_integrity_ok(_engine_conn(), "fts_tasks"))
        # Жалоба «malformed inverted index» при реально битом индексе:
        # авточинка пересобирает его из задач, вердикт становится ok.
        healed = db_module._heal_fts_verdicts(
            None, ["malformed inverted index for FTS5 table main.fts_tasks"]
        )
        self.assertEqual(healed, ["ok"])
        self.assertTrue(fts_integrity_ok(_engine_conn(), "fts_tasks"))
        # и поиск снова находит живую задачу
        response = client.get("/api/search", params={"q": MARK})
        self.assertEqual(response.status_code, 200, response.text)
        groups = {group["id"]: group for group in response.json()["groups"]}
        self.assertIn("tasks", groups)
        self.assertTrue(any(item["id"] == self.task["id"] for item in groups["tasks"]["items"]))

    def test_reindex_endpoint_rebuilds_everything(self):
        _break_fts_tasks()
        response = client.post("/api/system/db/reindex")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("fts_tasks", payload["detail"])
        self.assertTrue(fts_integrity_ok(_engine_conn(), "fts_tasks"))
        self.assertGreater(payload["size_bytes"], 0)

    def test_index_init_failure_degrades_to_log(self):
        # Если создание FTS-индекса падает — приложение обязано жить без
        # поиска, а не ронять старт. Раньше except-обработчик сам падал
        # NameError (log_scope/logger не были импортированы) и убивал
        # create_app() вместо мягкой деградации (патч AN).
        from unittest.mock import patch

        with patch(
            "app.core.search.ensure_search_index", side_effect=RuntimeError("boom")
        ):
            db_module._ensure_search_index()  # не должен бросить исключение


def _engine_conn():
    return db_module._engine.connect().execution_options(isolation_level="AUTOCOMMIT")


if __name__ == "__main__":
    unittest.main()
