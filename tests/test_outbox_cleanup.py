"""Гигиена очереди событий (патч AS): retention, дрен до пустой очереди, шина.

Что проверяем:

- cleanup_outbox удаляет DONE старше outbox.retention_days, FAILED —
  старше вчетверо, а свежие DONE и вечный PENDING не трогает;
- _drain_tick разбирает всплеск событий (45 при партии 20) за один такт,
  а не по одной партии на poll_seconds;
- /healthz показывает состояние шины живых событий (dropped/subscribers)
  — раньше переполнение очередей вкладок не было видно нигде.

Инициализация идемпотентна: при `unittest discover` первым импортируется
test_app (готовит env и конфиг); при одиночном запуске конфиг поднимаем сами.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta

_root = tempfile.mkdtemp(prefix="ws-outbox-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "outbox-test-secret")
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

from app.core.db import session_scope, utcnow  # noqa: E402
from app.core.events_catalog import PROJECT_CREATED  # noqa: E402
from app.core.models import OutboxEvent  # noqa: E402
from app.core.outbox import _drain_tick, cleanup_outbox, enqueue, stats  # noqa: E402

MARK = "obx" + os.urandom(4).hex()


def _row(status: str, age_days: float, marker: str) -> OutboxEvent:
    return OutboxEvent(
        event_type=PROJECT_CREATED,
        payload={"title": marker},
        status=status,
        attempts=1,
        next_attempt_at=utcnow(),
        created_at=utcnow() - timedelta(days=age_days),
    )


class OutboxCleanupTest(unittest.TestCase):
    def test_cleanup_respects_retention_windows(self):
        rows = [
            _row("done", 20, MARK + "-done-old"),  # старше retention (14) — уходит
            _row("done", 5, MARK + "-done-fresh"),  # свежий DONE — остаётся
            _row("failed", 20, MARK + "-failed-mid"),  # FAILED живёт вчетверо дольше — остаётся
            _row("failed", 60, MARK + "-failed-old"),  # старше 4×retention — уходит
            _row("pending", 60, MARK + "-pending-old"),  # PENDING не трогаем никогда
        ]
        with session_scope() as session:
            for row in rows:
                session.add(row)

        cleanup_outbox()

        from sqlalchemy import select

        with session_scope() as session:
            rows = session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == PROJECT_CREATED)).all()
            left = {
                row.payload.get("title")
                for row in rows
                if isinstance(row.payload, dict) and MARK in str(row.payload.get("title") or "")
            }
        self.assertEqual(
            left,
            {MARK + "-done-fresh", MARK + "-failed-mid", MARK + "-pending-old"},
        )

    def test_drain_tick_empties_backlog_in_one_pass(self):
        # 45 событий при партии 20 — раньше это три poll_seconds паузы,
        # теперь один такт до упора.
        with session_scope() as session:
            for index in range(45):
                enqueue(
                    session,
                    PROJECT_CREATED,
                    {"title": f"{MARK}-burst-{index}", "subject": f"{MARK}-burst-{index}"},
                    user_id=1,
                )
        processed = _drain_tick()
        self.assertGreaterEqual(processed, 45)
        self.assertEqual(stats()["pending"], 0)

    def test_healthz_shows_bus_state(self):
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("bus", payload)
        self.assertGreaterEqual(payload["bus"]["dropped"], 0)
        self.assertGreaterEqual(payload["bus"]["subscribers"], 0)


if __name__ == "__main__":
    unittest.main()
