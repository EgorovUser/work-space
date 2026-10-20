"""Один активный фокус (патч AL): глобальные эндпоинты таймера.

GET /api/time/running и POST /api/time/stop не привязаны к проекту — рельса
и помодоро спрашивают и останавливают таймер, не зная, где он запущен.
Проверяем форму ответа, стоп «из другого проекта» и 404 без таймера.
"""
from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-time-run-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "time-run-test-secret")
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

from app.main import app  # noqa: E402

client = TestClient(app)

PASSWORD = "tester-pass"


def _login() -> None:
    client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})


class RunningTimerTest(unittest.TestCase):
    def tearDown(self):
        client.post("/api/time/stop")
        client.post("/api/auth/logout")

    def test_requires_login(self):
        self.assertEqual(client.get("/api/time/running").status_code, 401)
        self.assertEqual(client.post("/api/time/stop").status_code, 401)

    def test_running_shape_and_stop_anywhere(self):
        _login()
        first = client.post("/api/projects", json={"name": "focus-alpha"}).json()
        task = client.post(
            f"/api/projects/{first['id']}/tasks", json={"title": "Задача фокуса"}
        ).json()

        # Без таймера — пусто, стоп — 404.
        empty = client.get("/api/time/running")
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertIsNone(empty.json()["running"])
        self.assertEqual(client.post("/api/time/stop").status_code, 404)

        started = client.post(
            f"/api/projects/{first['id']}/time/start",
            json={"task_id": task["id"], "note": "глубокая работа"},
        )
        self.assertEqual(started.status_code, 201, started.text)

        # Форма ответа: всё, что нужно рельсе — проект, задача, старт.
        running = client.get("/api/time/running").json()["running"]
        self.assertIsNotNone(running)
        self.assertTrue(running["running"])
        self.assertEqual(running["project_id"], first["id"])
        self.assertEqual(running["task_id"], task["id"])
        self.assertEqual(running["task_title"], "Задача фокуса")
        self.assertEqual(running["note"], "глубокая работа")
        self.assertIn("started_at", running)

        # Стоп без проекта — работает даже «из другого проекта»: точечный
        # /projects/N/time/stop для чужого проекта даёт 404, глобальный — нет.
        second = client.post("/api/projects", json={"name": "focus-beta"}).json()
        self.assertEqual(
            client.post(f"/api/projects/{second['id']}/time/stop").status_code, 404
        )
        stopped = client.post("/api/time/stop")
        self.assertEqual(stopped.status_code, 200, stopped.text)
        self.assertFalse(stopped.json()["running"])
        self.assertGreaterEqual(stopped.json()["minutes"], 0)

        # После стопа — снова пусто.
        self.assertIsNone(client.get("/api/time/running").json()["running"])

    def test_start_elsewhere_autostops(self):
        """Глобальный стоп не ломает автостоп старого таймера при новом старте."""
        _login()
        first = client.post("/api/projects", json={"name": "focus-gamma"}).json()
        second = client.post("/api/projects", json={"name": "focus-delta"}).json()

        one = client.post(f"/api/projects/{first['id']}/time/start", json={"note": "первый"})
        self.assertEqual(one.status_code, 201, one.text)
        two = client.post(f"/api/projects/{second['id']}/time/start", json={"note": "второй"})
        self.assertEqual(two.status_code, 201, two.text)
        # Автостоп погасил первый: идёт только второй.
        running = client.get("/api/time/running").json()["running"]
        self.assertEqual(running["project_id"], second["id"])
        self.assertEqual(running["note"], "второй")
