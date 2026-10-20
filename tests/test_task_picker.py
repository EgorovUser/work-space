"""Выбор задачи для помодоро поиском (патч AF): GET /api/tasks/search.

Ключевые инварианты:
- находятся только открытые задачи: закрытые (колонка «Готово»), удалённые
  в корзину и задачи архивных проектов в выдачу не попадают;
- совпадение — тот же FTS5, что у общего поиска: префикс слова, регистр
  не важен («УНИКУМ» найдёт «уникумный»);
- короткий запрос честно возвращает пустой список, а не всё подряд;
- аноним получает 401.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid

_root = tempfile.mkdtemp(prefix="ws-task-picker-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "task-picker-test-secret")
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


def _word() -> str:
    return "уникум" + uuid.uuid4().hex[:8]


def _closed_status(project_id: int) -> int:
    statuses = client.get(f"/api/projects/{project_id}/task-statuses").json()["items"]
    for item in statuses:
        if item["is_closed"]:
            return item["id"]
    raise AssertionError("в свежем проекте нет закрытой колонки")


class TaskPickerTest(unittest.TestCase):
    def tearDown(self):
        client.post("/api/auth/logout")

    def test_requires_login(self):
        self.assertEqual(client.get("/api/tasks/search", params={"q": "что-нибудь"}).status_code, 401)

    def test_finds_open_task_with_project_and_status(self):
        client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        word = _word()
        project = client.post("/api/projects", json={"name": "Пикер " + word}).json()
        created = client.post(
            f"/api/projects/{project['id']}/tasks", json={"title": f"Задача {word}"}
        ).json()

        response = client.get("/api/tasks/search", params={"q": word})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertTrue(any(item["id"] == created["id"] for item in items))
        mine = next(item for item in items if item["id"] == created["id"])
        self.assertEqual(mine["project_id"], project["id"])
        self.assertEqual(mine["project_name"], "Пикер " + word)
        self.assertEqual(mine["title"], f"Задача {word}")
        self.assertTrue(mine["status_name"])

    def test_match_is_prefix_and_case_insensitive(self):
        client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        word = _word()
        project = client.post("/api/projects", json={"name": "Пикер регистр"}).json()
        created = client.post(
            f"/api/projects/{project['id']}/tasks", json={"title": f"Задача {word}ный"}
        ).json()

        items = client.get("/api/tasks/search", params={"q": word.upper()}).json()["items"]
        self.assertTrue(any(item["id"] == created["id"] for item in items))

    def test_closed_trashed_and_archived_are_hidden(self):
        client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        word = _word()
        project = client.post("/api/projects", json={"name": "Пикер фильтры"}).json()
        closed = client.post(
            f"/api/projects/{project['id']}/tasks", json={"title": f"Закрытая {word}"}
        ).json()
        trashed = client.post(
            f"/api/projects/{project['id']}/tasks", json={"title": f"В корзине {word}"}
        ).json()

        client.patch(
            f"/api/projects/{project['id']}/tasks/{closed['id']}",
            json={"status_id": _closed_status(project["id"])},
        )
        client.delete(f"/api/projects/{project['id']}/tasks/{trashed['id']}")

        archived_project = client.post(
            "/api/projects", json={"name": "Пикер архив " + word}
        ).json()
        archived_task = client.post(
            f"/api/projects/{archived_project['id']}/tasks", json={"title": f"Из архива {word}"}
        ).json()
        client.post(f"/api/projects/{archived_project['id']}/archive", json={"archived": True})

        items = client.get("/api/tasks/search", params={"q": word}).json()["items"]
        ids = {item["id"] for item in items}
        self.assertNotIn(closed["id"], ids)
        self.assertNotIn(trashed["id"], ids)
        self.assertNotIn(archived_task["id"], ids)

    def test_empty_query_returns_empty_list(self):
        client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        for query in ("", " ", "   "):
            response = client.get("/api/tasks/search", params={"q": query})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"], [])
        # Одна буква — такой же префиксный запрос, как у общего поиска:
        # не ошибка и не «всё подряд», а честный поиск по префиксу.
        single = client.get("/api/tasks/search", params={"q": "у"})
        self.assertEqual(single.status_code, 200)
        self.assertIsInstance(single.json()["items"], list)

    def test_limit_is_clamped(self):
        client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
        word = _word()
        project = client.post("/api/projects", json={"name": "Пикер лимит"}).json()
        for index in range(3):
            client.post(
                f"/api/projects/{project['id']}/tasks", json={"title": f"{word} номер {index}"}
            )

        small = client.get("/api/tasks/search", params={"q": word, "limit": 2}).json()["items"]
        self.assertEqual(len(small), 2)
        # Отрицательный и гигантский лимиты прижимаются к границам, а не роняют запрос.
        weird = client.get("/api/tasks/search", params={"q": word, "limit": -5}).json()["items"]
        self.assertEqual(len(weird), 1)
        big = client.get("/api/tasks/search", params={"q": word, "limit": 9999}).json()["items"]
        self.assertEqual(len(big), 3)


if __name__ == "__main__":
    unittest.main()
