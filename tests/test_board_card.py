"""Карточка задачи на доске (патч R): чеклист и списанное время в списке.

Инварианты:
- каждый элемент GET /api/projects/{id}/tasks несёт пункты чеклиста
  (id, title, done, position — в порядке позиции) и spent_minutes;
- отмечание пункта видно на доске без перечитывания задачи;
- ручная запись времени (те же минуты, что шлёт ввод часов) суммируется
  в spent_minutes и на доске, и в карточке задачи;
- записи чужой задачи не подтекают в чужой spent_minutes.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

_root = tempfile.mkdtemp(prefix="ws-board-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "board-test-secret")
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
    response = client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
    assert response.status_code == 200, response.text


def _project(name: str) -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _task(project_id: int, title: str) -> dict:
    response = client.post(f"/api/projects/{project_id}/tasks", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def _board(project_id: int) -> dict:
    response = client.get(f"/api/projects/{project_id}/tasks")
    assert response.status_code == 200, response.text
    return response.json()


def _board_task(project_id: int, task_id: int) -> dict:
    items = [item for item in _board(project_id)["items"] if item["id"] == task_id]
    assert len(items) == 1, "задача должна попасть в список доски ровно один раз"
    return items[0]


class BoardCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _login()

    def test_board_carries_checklist_items_and_zero_spent(self) -> None:
        project = _project("Доска-карточка " + os.urandom(3).hex())
        task = _task(project["id"], "Карточка с чеклистом")
        for title in ("Первый", "Второй", "Третий"):
            response = client.post(
                f"/api/projects/{project['id']}/tasks/{task['id']}/checklist",
                json={"title": title},
            )
            assert response.status_code == 201, response.text

        card = _board_task(project["id"], task["id"])
        self.assertEqual([item["title"] for item in card["checklist"]], ["Первый", "Второй", "Третий"])
        self.assertTrue(all(item["done"] is False for item in card["checklist"]))
        self.assertEqual([item["position"] for item in card["checklist"]], [0, 1, 2])
        self.assertEqual(card["checklist_total"], 3)
        self.assertEqual(card["checklist_done"], 0)
        self.assertEqual(card["spent_minutes"], 0)

    def test_check_done_on_board_updates_counters(self) -> None:
        project = _project("Отметка с доски " + os.urandom(3).hex())
        task = _task(project["id"], "Отмечаем с доски")
        item = client.post(
            f"/api/projects/{project['id']}/tasks/{task['id']}/checklist",
            json={"title": "Пункт"},
        ).json()

        response = client.patch(
            f"/api/projects/{project['id']}/tasks/{task['id']}/checklist/{item['id']}",
            json={"done": True},
        )
        assert response.status_code == 200, response.text

        card = _board_task(project["id"], task["id"])
        self.assertTrue(card["checklist"][0]["done"])
        self.assertEqual(card["checklist_done"], 1)
        self.assertEqual(card["checklist_total"], 1)
        # Прогресс в автоматическом режиме = доля отмеченных.
        self.assertEqual(card["progress"], 100)

    def test_logged_minutes_sum_into_spent_on_board_and_task(self) -> None:
        project = _project("Часы на карточке " + os.urandom(3).hex())
        task = _task(project["id"], "Списываем часы")
        other = _task(project["id"], "Чужая задача")
        today = date.today().isoformat()

        # 1.5 часа → 90 минут: столько шлёт поле ввода часов на карточке.
        response = client.post(
            f"/api/projects/{project['id']}/time/entries",
            json={"task_id": task["id"], "minutes": 90, "day": today, "note": ""},
        )
        assert response.status_code == 201, response.text
        response = client.post(
            f"/api/projects/{project['id']}/time/entries",
            json={"task_id": task["id"], "minutes": 30, "day": today, "note": ""},
        )
        assert response.status_code == 201, response.text

        card = _board_task(project["id"], task["id"])
        self.assertEqual(card["spent_minutes"], 120)

        full = client.get(f"/api/projects/{project['id']}/tasks/{task['id']}").json()
        self.assertEqual(full["spent_minutes"], 120)
        self.assertEqual(full["checklist"], [])

        # Записи первой задачи не подтекают в соседнюю.
        neighbour = _board_task(project["id"], other["id"])
        self.assertEqual(neighbour["spent_minutes"], 0)


if __name__ == "__main__":
    unittest.main()
