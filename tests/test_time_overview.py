"""Сводка времени по всем проектам (патч S): /api/time/overview.

Проверяет границы недель (понедельник — воскресенье), распределение по
проектам, «что сделано» (записи с задачами) и разделение текущей и прошлой
недели. Тот же временный каталог, что у остальных HTTP-тестов: база общая,
поэтому сравниваем проектные куски, а не глобальные итоги.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_root = tempfile.mkdtemp(prefix="ws-time-ov-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "time-ov-test-secret")
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
ZONE = ZoneInfo("Europe/Moscow")  # дефолт core.ui.timezone


def _login() -> None:
    client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})


def _monday(offset_weeks: int) -> datetime:
    """Понедельник недели (по зоне приложения) со сдвигом на N недель назад."""
    today = datetime.now(ZONE).date()
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=offset_weeks)
    return datetime(monday.year, monday.month, monday.day, hour=10, tzinfo=ZONE)


class TimeOverviewTest(unittest.TestCase):
    def tearDown(self):
        client.post("/api/auth/logout")

    def test_requires_login(self):
        self.assertEqual(client.get("/api/time/overview").status_code, 401)

    def test_weeks_and_projects(self):
        _login()
        first = client.post("/api/projects", json={"name": "overview-alpha"}).json()
        second = client.post("/api/projects", json={"name": "overview-beta"}).json()

        current_day = _monday(0)
        previous_day = _monday(1)
        made = client.post(
            f"/api/projects/{first['id']}/time/entries",
            json={
                "started_at": current_day.isoformat(),
                "ended_at": (current_day + timedelta(minutes=120)).isoformat(),
                "note": "текущая неделя",
            },
        )
        self.assertEqual(made.status_code, 201, made.text)
        made = client.post(
            f"/api/projects/{second['id']}/time/entries",
            json={
                "started_at": previous_day.isoformat(),
                "ended_at": (previous_day + timedelta(minutes=90)).isoformat(),
                "note": "прошлая неделя",
            },
        )
        self.assertEqual(made.status_code, 201, made.text)

        response = client.get("/api/time/overview")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()

        # Границы недель: обе начинаются в понедельник и длятся 7 дней.
        self.assertEqual(data["week"]["starts_on"], 0)
        current = data["current_week"]
        previous = data["previous_week"]
        self.assertEqual(datetime.fromisoformat(current["start"]).weekday(), 0)
        self.assertEqual(
            datetime.fromisoformat(previous["start"]).weekday(), 0
        )
        self.assertEqual(
            datetime.fromisoformat(current["start"]) - datetime.fromisoformat(previous["start"]),
            timedelta(days=7),
        )

        # Записи попали в свои недели и в свои проекты.
        alpha_now = next(
            (item for item in current["projects"] if item["project_id"] == first["id"]), None
        )
        self.assertIsNotNone(alpha_now, "проект alpha не попал в текущую неделю")
        self.assertEqual(alpha_now["project_name"], "overview-alpha")
        self.assertGreaterEqual(alpha_now["minutes"], 120)
        notes = [entry["note"] for entry in alpha_now["entries"]]
        self.assertIn("текущая неделя", notes)
        self.assertTrue(
            all(entry["day"] >= current["start"] for entry in alpha_now["entries"])
        )

        beta_before = next(
            (item for item in previous["projects"] if item["project_id"] == second["id"]), None
        )
        self.assertIsNotNone(beta_before, "проект beta не попал в прошлую неделю")
        self.assertGreaterEqual(beta_before["minutes"], 90)
        self.assertIn(
            "прошлая неделя",
            [entry["note"] for entry in beta_before["entries"]],
        )

        # И наоборот: в чужих неделях этих записей нет.
        self.assertIsNone(
            next(
                (item for item in previous["projects"] if item["project_id"] == first["id"]),
                None,
            )
        )
        self.assertIsNone(
            next(
                (item for item in current["projects"] if item["project_id"] == second["id"]),
                None,
            )
        )

    def test_entry_with_task_title(self):
        _login()
        project = client.post("/api/projects", json={"name": "overview-gamma"}).json()
        task = client.post(
            f"/api/projects/{project['id']}/tasks",
            json={"title": "задача сводки"},
        ).json()

        day = _monday(0) + timedelta(days=1)
        made = client.post(
            f"/api/projects/{project['id']}/time/entries",
            json={
                "started_at": day.isoformat(),
                "ended_at": (day + timedelta(minutes=30)).isoformat(),
                "task_id": task["id"],
            },
        )
        self.assertEqual(made.status_code, 201, made.text)

        data = client.get("/api/time/overview").json()
        block = next(
            item
            for item in data["current_week"]["projects"]
            if item["project_id"] == project["id"]
        )
        entry = next(item for item in block["entries"] if item["id"] == made.json()["id"])
        self.assertEqual(entry["task_title"], "задача сводки")
        self.assertEqual(entry["task_id"], task["id"])


if __name__ == "__main__":
    unittest.main()
