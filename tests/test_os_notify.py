"""Системные уведомления (патч AO): событие notifications.new и канал os.

Что проверяем:

- канал os появляется в каталоге и по умолчанию выключен — включается
  осознанно, потому что требует разрешения браузера;
- handle() после создания уведомления публикует адресное событие
  notifications.new: заголовок, ссылка и флаг os из матрицы пользователя;
- канал os не создаёт строк очереди доставок (мимолётный тост нечего
  ретраить и догонять) — как и канал browser;
- SSE-канал пересылает notifications.new именованным событием: вкладка
  получает само уведомление, а не только пересчёт счётчика.

Инициализация идемпотентна: при `unittest discover` первым импортируется
test_app (готовит env и конфиг); при одиночном запуске конфиг поднимаем сами.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-os-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "os-test-secret")
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

from app.main import app  # noqa: E402  (импорт поднимает init_db + seed)

client = TestClient(app)

from sqlalchemy import select  # noqa: E402

from app.core import events_bus  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.core.events_catalog import PROJECT_CREATED  # noqa: E402
from app.core.outbox import dispatch_once, enqueue  # noqa: E402
from app.core.settings_store import reset_value, set_value  # noqa: E402
from app.modules.notifications.models import NotificationDelivery  # noqa: E402

PASSWORD = "tester-pass"
MARK = "os" + os.urandom(4).hex()


def _drain_all() -> None:
    # Общая база discover-прогона: соседние модули оставляют события в
    # аутбоксе, dispatch_once берёт партию по 20 — крутим до упора.
    for _ in range(60):
        if dispatch_once() == 0:
            break


def _enqueue_event(title: str) -> None:
    with session_scope() as session:
        enqueue(
            session,
            PROJECT_CREATED,
            {"title": title, "subject": title},
            user_id=1,
        )
    _drain_all()


def _collect(q, title: str) -> list:
    """События notifications.new с нашим заголовком (база общая — чужие молча пропускаем)."""
    fresh = []
    while True:
        try:
            item = q.get(timeout=0.3)
        except Exception:
            break
        if item.type == "notifications.new" and str(item.payload.get("title", "")).find(title) >= 0:
            fresh.append(item)
    return fresh


class OsNotifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})

    @classmethod
    def tearDownClass(cls):
        reset_value("notifications", "matrix", "user", actor_id=1, user_id=1)
        client.post("/api/auth/logout")

    def test_os_channel_in_meta_off_by_default(self):
        # Алфавитный порядок: этот тест бежит после соседей, включавших
        # канал в user-матрице, — сбрасываем её к дефолту.
        reset_value("notifications", "matrix", "user", actor_id=1, user_id=1)
        response = client.get("/api/notifications/meta")
        self.assertEqual(response.status_code, 200, response.text)
        meta = response.json()
        ids = [item["id"] for item in meta["channels"]]
        self.assertIn("os", ids)
        labels = {item["id"]: item["label"] for item in meta["channels"]}
        self.assertEqual(labels["os"], "Системные уведомления")
        # по умолчанию канал выключен у всех событий
        for flags in meta["matrix"].values():
            self.assertFalse(flags.get("os"))

    def test_handle_publishes_new_event_with_os_flag(self):
        set_value(
            "notifications",
            "matrix",
            "user",
            {"project.created": {"browser": True, "os": True}},
            actor_id=1,
            user_id=1,
        )
        title = "os-проект " + MARK
        # Дрен чужого хвоста ДО подписки: каждый обработанный аутбокс
        # раздаёт по шине notifications.new/changed, а очередь подписчика
        # ограничена 200 — на общем discover-прогоне наше событие утонуло
        # бы в этом потоке и молча дропнулось.
        _drain_all()
        with events_bus.subscribe(1) as q:
            _enqueue_event(title)
            fresh = _collect(q, title)
        self.assertTrue(fresh, "событие notifications.new не опубликовано")
        payload = fresh[0].payload
        self.assertIn(title, payload["title"])
        self.assertTrue(payload["os"])
        self.assertIn("link", payload)
        self.assertEqual(payload["event_type"], "project.created")

    def test_handle_publishes_new_event_os_off_by_default(self):
        reset_value("notifications", "matrix", "user", actor_id=1, user_id=1)
        title = "os-тихий " + MARK
        _drain_all()
        with events_bus.subscribe(1) as q:
            _enqueue_event(title)
            fresh = _collect(q, title)
        self.assertTrue(fresh, "событие notifications.new не опубликовано")
        self.assertFalse(fresh[0].payload["os"])

    def test_os_channel_creates_no_delivery_rows(self):
        set_value(
            "notifications",
            "matrix",
            "user",
            {"project.created": {"browser": False, "os": True, "telegram": False, "email": False}},
            actor_id=1,
            user_id=1,
        )
        title = "os-без-очереди " + MARK
        _enqueue_event(title)
        with session_scope() as session:
            rows = session.scalars(
                select(NotificationDelivery).where(NotificationDelivery.channel == "os")
            ).all()
            self.assertEqual(rows, [])

    def test_sse_forwards_notifications_new(self):
        with client.stream("GET", "/api/events") as response:
            self.assertEqual(response.status_code, 200)
            lines = response.iter_lines()

            def read_event():
                name = None
                for line in lines:
                    if line.startswith("event: "):
                        name = line[7:]
                    elif line.startswith("data: ") and name:
                        return name, json.loads(line[6:])
                return None, None

            name, _ = read_event()
            self.assertEqual(name, "state")

            events_bus.publish(
                "notifications.new",
                {"id": 1, "title": "SSE-тост", "body": "", "link": "/mail", "os": True},
                user_id=1,
            )
            name, payload = read_event()
            self.assertEqual(name, "notifications.new")
            self.assertEqual(payload["title"], "SSE-тост")
            self.assertTrue(payload["os"])


if __name__ == "__main__":
    unittest.main()
