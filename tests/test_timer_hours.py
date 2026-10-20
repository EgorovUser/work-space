"""Джоба «час по таймеру» (патч AM): уведомление на каждый полный час.

Таймер заводим через API, откатываем старт назад прямой правкой строки
(сервис считает часы от started_at), гоним джобу и дренёр аутбокса.
Проверяем тексты (час/часа), предмет с задачей, дедуп на повторном
проходе и тишину для короткого таймера.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta

_root = tempfile.mkdtemp(prefix="ws-time-hours-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "time-hours-test-secret")
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

from app.core.db import session_scope, utcnow  # noqa: E402
from app.core.outbox import dispatch_once  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.timetracking.models import TimeEntry  # noqa: E402
from app.modules.timetracking.service import notify_hours_open  # noqa: E402

client = TestClient(app)

PASSWORD = "tester-pass"


def _login() -> None:
    client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})


def _backdate(entry_id: int, hours: float) -> None:
    with session_scope() as session:
        row = session.get(TimeEntry, entry_id)
        row.started_at = utcnow() - timedelta(hours=hours)


def _drain_all() -> None:
    # Соседние модули оставляют в аутбоксе сотни событий (общая база
    # discover-прогона), а dispatch_once берёт партию по 20: крутим до
    # упора, иначе наши свежие «часовые» события не дойдут до ленты.
    for _ in range(60):
        if dispatch_once() == 0:
            break


def _hour_notes(project_id: int) -> list[dict]:
    """Уведомления «час по таймеру» только этого проекта: база у модуля
    общая, тесты не должны видеть чужие таймеры."""
    feed = client.get("/api/notifications").json()
    prefix = "/projects/{}/".format(project_id)
    return [item for item in feed["items"] if item["event_type"] == "time.hour_passed" and item["link"].startswith(prefix)]


class TimerHoursTest(unittest.TestCase):
    def tearDown(self):
        client.post("/api/time/stop")
        client.post("/api/auth/logout")

    def test_short_timer_is_silent(self):
        _login()
        project = client.post("/api/projects", json={"name": "hours-short"}).json()
        started = client.post(f"/api/projects/{project['id']}/time/start", json={"note": "только начался"})
        self.assertEqual(started.status_code, 201, started.text)

        notify_hours_open()
        _drain_all()
        self.assertEqual(_hour_notes(project["id"]), [])

    def test_hour_notifications_with_dedup(self):
        _login()
        project = client.post("/api/projects", json={"name": "hours-alpha"}).json()
        task = client.post(
            f"/api/projects/{project['id']}/tasks", json={"title": "Долгая работа"}
        ).json()
        started = client.post(
            f"/api/projects/{project['id']}/time/start",
            json={"task_id": task["id"], "note": "заметка фокуса"},
        )
        self.assertEqual(started.status_code, 201, started.text)
        _backdate(started.json()["entry"]["id"], 2.1)

        notify_hours_open()
        _drain_all()
        notes = _hour_notes(project["id"])
        titles = [note["title"] for note in notes]
        self.assertEqual(titles, ["По таймеру прошёл 2 часа", "По таймеру прошёл 1 час"])
        for note in notes:
            self.assertEqual(note["event_label"], "Час по таймеру")
            self.assertIn("Задача «Долгая работа»", note["body"])
            self.assertEqual(note["link"], f"/projects/{project['id']}/tasks/{task['id']}")

        # Повторный проход джобы не плодит дубли: ни в аутбоксе, ни в ленте.
        notify_hours_open()
        _drain_all()
        self.assertEqual(len(_hour_notes(project["id"])), 2)

    def test_note_instead_of_task(self):
        _login()
        project = client.post("/api/projects", json={"name": "hours-beta"}).json()
        started = client.post(
            f"/api/projects/{project['id']}/time/start", json={"note": "разбор почты"}
        )
        self.assertEqual(started.status_code, 201, started.text)
        _backdate(started.json()["entry"]["id"], 1.2)

        notify_hours_open()
        _drain_all()
        notes = _hour_notes(project["id"])
        self.assertEqual([note["title"] for note in notes], ["По таймеру прошёл 1 час"])
        self.assertIn("разбор почты", notes[0]["body"])
        self.assertEqual(notes[0]["link"], f"/projects/{project['id']}/time")
