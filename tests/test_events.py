"""Живые события: шина в процессе и SSE-канал /api/events.

Шина проверяется напрямую (доставка, адресность, переполнение). Канал —
через TestClient: аноним получает 401, вошедший — стартовое состояние,
сигналы из шины пересчитывают счётчики и доходят до вкладки.

Инициализация идемпотентна: при `unittest discover` первым импортируется
test_app (готовит env и конфиг); при одиночном запуске конфиг поднимаем сами.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-events-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "events-test-secret")
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
# Отдельный клиент без cookie: «аноним» не должен случайно получить открытый канал.
anon_client = TestClient(app)

from app.core import events_bus  # noqa: E402
from app.core.db import session_scope, utcnow  # noqa: E402
from app.core.settings_store import set_value  # noqa: E402
from app.modules.mail.models import MailMessage  # noqa: E402
from app.modules.notifications.models import Notification  # noqa: E402

PASSWORD = "tester-pass"


class BusTest(unittest.TestCase):
    def test_broadcast_reaches_subscriber(self):
        with events_bus.subscribe(1) as q:
            events_bus.publish("mail.changed")
            event = q.get(timeout=1)
        self.assertEqual(event.type, "mail.changed")
        self.assertEqual(event.payload, {})

    def test_targeted_event_skips_other_users(self):
        with events_bus.subscribe(1) as first, events_bus.subscribe(2) as second:
            events_bus.publish("notifications.changed", {"n": 1}, user_id=2)
            hit = second.get(timeout=1)
            self.assertEqual(hit.type, "notifications.changed")
            self.assertEqual(hit.payload, {"n": 1})
            with self.assertRaises(Exception):
                first.get(timeout=0.2)

    def test_full_queue_drops_instead_of_blocking(self):
        before = events_bus.dropped()
        with events_bus.subscribe(7) as q:
            for _ in range(events_bus.QUEUE_LIMIT + 50):
                events_bus.publish("mail.changed")
        # паблишер не упал, переполнение учтено, подписка жива дальше
        self.assertGreater(events_bus.dropped(), before)
        with events_bus.subscribe(7) as q2:
            events_bus.publish("mail.changed")
            self.assertEqual(q2.get(timeout=1).type, "mail.changed")


class SseHttpTest(unittest.TestCase):
    mail_ids: list[int] = []
    notification_ids: list[int] = []

    @classmethod
    def setUpClass(cls):
        client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        set_value("core", "events.heartbeat_seconds", "global", 5, actor_id=1)

    @classmethod
    def tearDownClass(cls):
        # прибираем за собой: письма и уведомления, созданные напрямую в базе
        with session_scope() as session:
            for row_id in cls.mail_ids:
                row = session.get(MailMessage, row_id)
                if row is not None:
                    session.delete(row)
            for row_id in cls.notification_ids:
                row = session.get(Notification, row_id)
                if row is not None:
                    session.delete(row)
        set_value("core", "events.heartbeat_seconds", "global", 20, actor_id=1)
        client.post("/api/auth/logout")

    def test_anonymous_gets_401(self):
        response = anon_client.get("/api/events")
        self.assertEqual(response.status_code, 401)

    def test_disabled_events_get_503(self):
        set_value("core", "events.enabled", "global", False, actor_id=1)
        try:
            response = client.get("/api/events")
            self.assertEqual(response.status_code, 503)
            self.assertIn("выключены", response.json()["detail"])
        finally:
            set_value("core", "events.enabled", "global", True, actor_id=1)

    def test_stream_counts_follow_signals(self):
        with client.stream("GET", "/api/events") as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers.get("content-type", ""))
            lines = response.iter_lines()

            def read_event():
                name = None
                for line in lines:
                    if line.startswith("event: "):
                        name = line[7:]
                    elif line.startswith("data: ") and name:
                        return name, json.loads(line[6:])
                return None, None

            name, state = read_event()
            self.assertEqual(name, "state")
            self.assertIn("mail_unread", state)
            self.assertIn("notifications_unread", state)
            base_mail = state["mail_unread"]
            base_notify = state["notifications_unread"]

            # письмо появилось в базе (так его оставил бы poll_accounts) — сигнал
            with session_scope() as session:
                row = MailMessage(
                    project_id=0,
                    folder="INBOX",
                    subject="SSE-тест",
                    from_addr="sse@test",
                    body="текст",
                    received_at=utcnow(),
                )
                session.add(row)
                session.flush()
                self.mail_ids.append(row.id)
            events_bus.publish("mail.changed")
            name, state = read_event()
            self.assertEqual(name, "state")
            self.assertEqual(state["mail_unread"], base_mail + 1)

            # забор ящика принёс письма — вкладке уходит событие с деталями
            events_bus.publish("mail.sync", {"account_id": 1, "account": "Рабочий", "fetched": 3})
            name, payload = read_event()
            self.assertEqual(name, "mail.sync")
            self.assertEqual(payload, {"account_id": 1, "account": "Рабочий", "fetched": 3})

            # новое уведомление — счётчик дёргается адресным сигналом
            with session_scope() as session:
                row = Notification(
                    user_id=1,
                    event_type="mail.new",
                    title="SSE-уведомление",
                    body="",
                    link="/mail",
                    show_browser=True,
                    read=False,
                    created_at=utcnow(),
                )
                session.add(row)
                session.flush()
                self.notification_ids.append(row.id)
            events_bus.publish("notifications.changed", user_id=1)
            name, state = read_event()
            self.assertEqual(name, "state")
            self.assertEqual(state["notifications_unread"], base_notify + 1)


if __name__ == "__main__":
    unittest.main()
