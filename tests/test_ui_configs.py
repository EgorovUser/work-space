"""Конфигурации страниц интерфейса (визуальный редактор, патч AW).

Дефолт по настройкам, нормализация по каталогу (whitelist), заглушки для
неизвестных элементов, ревизии с неразрушающим откатом, сброс, сигнал
шине для SSE-синхронизации вкладок.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-ui-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "ui-test-secret")
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
from app.core import events_bus  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.ui.models import UiConfig, UiConfigRevision  # noqa: E402

client = TestClient(app)

# Ожидаемый дефолт «Сегодня»: порядок каталога, все элементы со всеми
# свойствами (дефолты влиты).
DEFAULT_ELEMENTS = [
    "overdue-tasks",
    "upcoming-tasks",
    "pomodoro",
    "mail-events",
    "new-mail",
    "notifications",
    "projects",
]


class UiConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client.post("/api/auth/login", json={"username": "tester", "password": "tester-pass"})
        me = client.get("/api/auth/me").json()
        cls.user_id = me["id"]

    def setUp(self):
        # Каждый тест стартует с чистым листом: конфиг и история —
        # общие на пользователя, остатки прошлого теста мешают.
        # SessionLocal берём через модуль в момент вызова — при импорте
        # файла он ещё None (инициализируется в init_db при старте приложения).
        with db_module.SessionLocal() as session:
            session.query(UiConfigRevision).delete()
            session.query(UiConfig).delete()
            session.commit()

    @classmethod
    def tearDownClass(cls):
        # Вернуть скрытые настройками секции — другие тесты ждут дефолт.
        client.post(
            "/api/settings/reset",
            json={"module": "projects", "key": "home.show_tasks", "scope": "global"},
        )
        client.post("/api/auth/logout")

    def test_default_state_and_catalog(self):
        state = client.get("/api/ui/today").json()
        self.assertTrue(state["is_default"])
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual([item["element"] for item in state["items"]], DEFAULT_ELEMENTS)
        # Каждый элемент приходит со всеми свойствами схемы — фронт не
        # достраивает дефолты сам.
        for item in state["items"]:
            self.assertIn("span", item)
            self.assertIn("hidden", item)
            self.assertIn("title", item)
            if item["element"] != "pomodoro":
                self.assertIn("density", item)
        # Каталог для инспектора: элементы и схемы свойств.
        elements = {element["name"]: element for element in state["catalog"]["elements"]}
        self.assertEqual(len(elements), 7)
        prop_keys = [prop["key"] for prop in elements["pomodoro"]["props"]]
        self.assertIn("span", prop_keys)
        self.assertIn("hidden", prop_keys)
        self.assertIn("title", prop_keys)
        self.assertNotIn("density", prop_keys)  # у помодоро нет плотности

    def test_unknown_page_404(self):
        self.assertEqual(client.get("/api/ui/nope").status_code, 404)
        self.assertEqual(client.put("/api/ui/nope", json={"items": []}).status_code, 404)
        self.assertEqual(client.post("/api/ui/nope/reset").status_code, 404)

    def test_save_normalizes_and_persists(self):
        saved = client.put(
            "/api/ui/today",
            json={
                "items": [
                    # span вне списка → дефолт элемента; мусорные ключи долой,
                    # отсутствующие свойства — дефолты.
                    {"element": "projects", "span": 99, "junk": "x"},
                    {"element": "pomodoro", "span": 4, "hidden": "yes"},
                    {"element": "new-mail", "span": 3, "title": "  Почта  ", "density": "tight"},
                ]
            },
        ).json()
        self.assertFalse(saved["is_default"])
        by_name = {item["element"]: item for item in saved["items"]}
        self.assertEqual(by_name["projects"]["span"], 4)  # дефолт projects
        self.assertEqual(by_name["projects"].get("junk"), None)
        self.assertFalse(by_name["projects"]["hidden"])
        self.assertEqual(by_name["pomodoro"]["span"], 4)
        self.assertFalse(by_name["pomodoro"]["hidden"])  # "yes" не bool → дефолт
        self.assertEqual(by_name["new-mail"]["title"], "Почта")  # обрезан и очишен
        self.assertEqual(by_name["new-mail"]["density"], "normal")  # не из списка
        self.assertEqual(by_name["new-mail"]["span"], 3)
        # Порядок сохранён как присланный.
        self.assertEqual(
            [item["element"] for item in saved["items"]],
            ["projects", "pomodoro", "new-mail"],
        )
        # Пережило перечитывание.
        again = client.get("/api/ui/today").json()
        self.assertEqual(again["items"], saved["items"])

    def test_unknown_element_saved_as_stub(self):
        # Стиль Home Assistant «card not found»: незнакомый элемент не
        # выбрасывается — хранится заглушкой с общими свойствами раскладки.
        saved = client.put(
            "/api/ui/today",
            json={"items": [{"element": "future-card", "span": 2, "custom": 1}]},
        ).json()
        stub = saved["items"][0]
        self.assertEqual(stub["element"], "future-card")
        self.assertEqual(stub["span"], 2)
        self.assertFalse(stub["hidden"])
        self.assertNotIn("custom", stub)

    def test_duplicates_and_garbage_dropped(self):
        saved = client.put(
            "/api/ui/today",
            json={
                "items": [
                    {"element": 42},  # не строка — элемент пропускается
                    {"element": "pomodoro"},
                    {"element": "pomodoro", "span": 4},  # дубль — выброшен
                    {"no_element": True},
                    {"element": "notifications", "span": 4},
                ]
            },
        ).json()
        self.assertEqual(
            [item["element"] for item in saved["items"]],
            ["pomodoro", "notifications"],
        )
        client.post("/api/ui/today/reset")

    def test_revisions_snapshot_and_restore(self):
        # Первый сейв: сохранять нечего — ревизий нет.
        first = client.put("/api/ui/today", json={"items": [{"element": "pomodoro", "span": 2}]}).json()
        self.assertEqual(client.get("/api/ui/today/revisions").json()["items"], [])
        # Второй сейв меняет раскладку — прежняя становится снимком.
        second = client.put("/api/ui/today", json={"items": [{"element": "pomodoro", "span": 4}]}).json()
        revisions = client.get("/api/ui/today/revisions").json()["items"]
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]["elements"], ["pomodoro"])
        # Повтор того же сейва — реальных изменений нет, история не растёт.
        client.put("/api/ui/today", json={"items": [{"element": "pomodoro", "span": 4}]}).json()
        self.assertEqual(len(client.get("/api/ui/today/revisions").json()["items"]), 1)
        # Откат не разрушающий: текущее (span 4) тоже станет снимком,
        # страница вернётся к span 2.
        restored = client.post(
            "/api/ui/today/revisions/{}/restore".format(revisions[0]["id"])
        ).json()
        self.assertEqual(restored["items"][0]["span"], 2)
        after = client.get("/api/ui/today/revisions").json()["items"]
        self.assertEqual(len(after), 2)
        self.assertEqual(after[0]["elements"], ["pomodoro"])  # снимок span 4
        # Откат к несуществующей ревизии — 404.
        self.assertEqual(
            client.post("/api/ui/today/revisions/999999/restore").status_code, 404
        )
        client.post("/api/ui/today/reset")

    def test_reset_keeps_history_restorable(self):
        client.put("/api/ui/today", json={"items": [{"element": "pomodoro", "span": 1}]})
        client.put("/api/ui/today", json={"items": [{"element": "notifications", "span": 2}]})
        reset = client.post("/api/ui/today/reset").json()
        self.assertTrue(reset["is_default"])
        self.assertEqual([item["element"] for item in reset["items"]], DEFAULT_ELEMENTS)
        # История пережила сброс: снимок прежней раскладки доступен и после
        # удаления строки конфига.
        revisions = client.get("/api/ui/today/revisions").json()["items"]
        self.assertTrue(revisions)
        restored = client.post(
            "/api/ui/today/revisions/{}/restore".format(revisions[0]["id"])
        ).json()
        self.assertEqual(
            [item["element"] for item in restored["items"]], ["notifications"]
        )
        client.post("/api/ui/today/reset")

    def test_default_respects_hidden_section_settings(self):
        # Кто выключил секции настройками, получает «Сегодня» без них —
        # как до редактора (визуально то же поведение, что data.sections).
        put = client.put(
            "/api/settings",
            json={
                "module": "projects",
                "key": "home.show_tasks",
                "scope": "global",
                "value": False,
            },
        )
        self.assertEqual(put.status_code, 200)
        state = client.get("/api/ui/today").json()
        names = [item["element"] for item in state["items"]]
        self.assertNotIn("overdue-tasks", names)
        self.assertNotIn("upcoming-tasks", names)
        self.assertIn("pomodoro", names)
        client.post(
            "/api/settings/reset",
            json={"module": "projects", "key": "home.show_tasks", "scope": "global"},
        )
        names = [item["element"] for item in client.get("/api/ui/today").json()["items"]]
        self.assertIn("overdue-tasks", names)

    def test_save_publishes_ui_changed(self):
        with events_bus.subscribe(self.user_id) as q:
            client.put("/api/ui/today", json={"items": [{"element": "pomodoro", "span": 3}]})
            event = q.get(timeout=2)
        self.assertEqual(event.type, "ui.changed")
        self.assertEqual(event.payload, {"page": "today"})
        # Сброс тоже сигналит вкладкам.
        with events_bus.subscribe(self.user_id) as q:
            client.post("/api/ui/today/reset")
            event = q.get(timeout=2)
        self.assertEqual(event.type, "ui.changed")
        client.post("/api/ui/today/reset")

    def test_revision_prune_by_setting(self):
        # Глубина истории — настройка: подрезаем до 2 и проверяем хвост.
        client.put("/api/settings", json={"module": "ui", "key": "history.keep_revisions", "scope": "global", "value": 2})
        try:
            for span in (1, 2, 3, 4):
                client.put("/api/ui/today", json={"items": [{"element": "pomodoro", "span": span}]})
            revisions = client.get("/api/ui/today/revisions").json()["items"]
            self.assertEqual(len(revisions), 2)
        finally:
            client.post("/api/settings/reset", json={"module": "ui", "key": "history.keep_revisions", "scope": "global"})
        client.post("/api/ui/today/reset")

    def test_auth_required(self):
        client.post("/api/auth/logout")
        self.assertEqual(client.get("/api/ui/today").status_code, 401)
        client.post("/api/auth/login", json={"username": "tester", "password": "tester-pass"})


if __name__ == "__main__":
    unittest.main()
