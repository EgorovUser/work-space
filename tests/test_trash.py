"""Корзина (патч N): мягкое удаление, восстановление, очистка.

Инварианты:
- удалённое исчезает из списков, карточек, «Сегодня» и FTS-поиска;
- корзина показывает запись с проектом и датой удаления;
- восстановление возвращает запись в рабочие списки целой;
- DELETE /api/trash/{kind}/{id} вычищает окончательно;
- джоба purge_expired убирает только просроченное по retention;
- анониму везде 401.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta

_root = tempfile.mkdtemp(prefix="ws-trash-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "trash-test-secret")
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

MARK = "trash" + os.urandom(4).hex()


def _login() -> None:
    client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})


def _project(name: str) -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _task(project_id: int, title: str, **extra) -> dict:
    body = {"title": title}
    body.update(extra)
    response = client.post(f"/api/projects/{project_id}/tasks", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _secret(project_id: int, title: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/secrets",
        json={"title": title, "secret": "para-" + MARK, "username": "user-" + MARK},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _document(project_id: int, title: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (MARK + ".txt", ("документ " + MARK).encode(), "text/plain")},
        data={"title": title, "note": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _rdp(project_id: int, name: str) -> dict:
    response = client.post(f"/api/projects/{project_id}/rdp", json={"name": name, "host": "10.0.0.7"})
    assert response.status_code == 201, response.text
    return response.json()


class TrashAuthTest(unittest.TestCase):
    def test_anonymous_gets_401(self):
        client.post("/api/auth/logout")
        self.assertEqual(client.get("/api/trash").status_code, 401)
        self.assertEqual(client.post("/api/trash/tasks/1/restore").status_code, 401)
        self.assertEqual(client.delete("/api/trash/tasks/1").status_code, 401)


class TrashTaskTest(unittest.TestCase):
    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.project = _project("Корзина задач " + MARK)
        self.task = _task(self.project["id"], "Задача в корзину " + MARK, deadline="2026-01-10T10:00:00")

    def _board_titles(self) -> list[str]:
        payload = client.get(f"/api/projects/{self.project['id']}/tasks").json()
        return [item["title"] for item in payload["items"]]

    def test_delete_hides_everywhere_and_restore_brings_back(self):
        base = f"/api/projects/{self.project['id']}/tasks/{self.task['id']}"

        # До удаления: задача на доске, в «Сегодня» и в поиске.
        self.assertIn(self.task["title"], self._board_titles())
        self.assertIn(self.task["title"], [item["title"] for item in client.get("/api/home").json()["tasks"]])
        found = client.get("/api/search", params={"q": MARK, "limit": 20}).json()
        self.assertTrue(any(group["id"] == "tasks" for group in found["groups"]))

        self.assertEqual(client.delete(base).status_code, 204)

        # Скрыта со всех экранов.
        self.assertEqual(client.get(base).status_code, 404)
        self.assertNotIn(self.task["title"], self._board_titles())
        self.assertNotIn(self.task["title"], [item["title"] for item in client.get("/api/home").json()["tasks"]])
        found = client.get("/api/search", params={"q": MARK, "limit": 20}).json()
        self.assertFalse(any(group["id"] == "tasks" for group in found["groups"]))

        # Но жива в корзине — и возвращается целиком.
        trash = client.get("/api/trash").json()
        group = next((item for item in trash["groups"] if item["id"] == "tasks"), None)
        self.assertIsNotNone(group)
        entry = next((item for item in group["items"] if item["id"] == self.task["id"]), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["project_id"], self.project["id"])
        self.assertTrue(entry["deleted_at"])

        self.assertEqual(
            client.post(f"/api/trash/tasks/{self.task['id']}/restore").status_code, 200
        )
        self.assertEqual(client.get(base).status_code, 200)
        self.assertIn(self.task["title"], self._board_titles())

    def test_purge_removes_forever(self):
        self.assertEqual(client.delete(f"/api/projects/{self.project['id']}/tasks/{self.task['id']}").status_code, 204)
        self.assertEqual(client.delete(f"/api/trash/tasks/{self.task['id']}").status_code, 204)
        self.assertEqual(client.post(f"/api/trash/tasks/{self.task['id']}/restore").status_code, 404)

    def test_restore_of_live_task_is_404(self):
        self.assertEqual(client.post(f"/api/trash/tasks/{self.task['id']}/restore").status_code, 404)


class TrashOtherKindsTest(unittest.TestCase):
    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.project = _project("Корзина разное " + MARK)

    def test_secret_roundtrip(self):
        secret = _secret(self.project["id"], "Секрет в корзину " + MARK)
        self.assertEqual(
            client.delete(f"/api/projects/{self.project['id']}/secrets/{secret['id']}").status_code, 204
        )
        self.assertEqual(client.get(f"/api/projects/{self.project['id']}/secrets/{secret['id']}").status_code, 404)
        names = [item["title"] for item in client.get(f"/api/projects/{self.project['id']}/secrets").json()["items"]]
        self.assertNotIn(secret["title"], names)
        global_names = [
            item["title"]
            for group in client.get("/api/secrets").json().get("groups", [])
            for item in group["items"]
        ]
        self.assertNotIn(secret["title"], global_names)

        self.assertEqual(client.post(f"/api/trash/secrets/{secret['id']}/restore").status_code, 200)
        restored = client.get(f"/api/projects/{self.project['id']}/secrets/{secret['id']}").json()
        self.assertEqual(restored["title"], secret["title"])
        # Значение сохранилось: reveal возвращает то, что записывали.
        revealed = client.post(f"/api/projects/{self.project['id']}/secrets/{secret['id']}/reveal").json()
        self.assertEqual(revealed["secret"], "para-" + MARK)

    def test_document_roundtrip(self):
        document = _document(self.project["id"], "Документ в корзину " + MARK)
        self.assertEqual(
            client.delete(f"/api/projects/{self.project['id']}/documents/{document['id']}").status_code, 204
        )
        self.assertEqual(client.get(f"/api/projects/{self.project['id']}/documents/{document['id']}").status_code, 404)
        self.assertEqual(client.post(f"/api/trash/documents/{document['id']}/restore").status_code, 200)
        payload = client.get(f"/api/projects/{self.project['id']}/documents/{document['id']}").json()
        self.assertEqual(payload["title"], document["title"])

    def test_rdp_roundtrip(self):
        row = _rdp(self.project["id"], "RDP в корзину " + MARK)
        self.assertEqual(client.delete(f"/api/projects/{self.project['id']}/rdp/{row['id']}").status_code, 204)
        self.assertEqual(client.get(f"/api/projects/{self.project['id']}/rdp/{row['id']}").status_code, 404)
        self.assertEqual(client.post(f"/api/trash/rdp/{row['id']}/restore").status_code, 200)
        names = [item["name"] for item in client.get(f"/api/projects/{self.project['id']}/rdp").json()["items"]]
        self.assertIn("RDP в корзину " + MARK, names)

    def test_unknown_kind_is_404(self):
        self.assertEqual(client.post("/api/trash/examples/1/restore").status_code, 404)
        self.assertEqual(client.delete("/api/trash/examples/1").status_code, 404)


class TrashPurgeJobTest(unittest.TestCase):
    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.project = _project("Корзина джоба " + MARK)

    def test_expired_is_purged_and_fresh_kept(self):
        from app.core.db import session_scope, utcnow
        from app.modules.tasks.models import Task as TaskModel
        from app.modules.trash.router import purge_expired

        old = _task(self.project["id"], "Старая из корзины " + MARK)
        fresh = _task(self.project["id"], "Свежая из корзины " + MARK)
        client.delete(f"/api/projects/{self.project['id']}/tasks/{old['id']}")
        client.delete(f"/api/projects/{self.project['id']}/tasks/{fresh['id']}")

        with session_scope() as session:
            row = session.get(TaskModel, old["id"])
            row.deleted_at = utcnow() - timedelta(days=365)
            session.flush()

        purge_expired()

        trash = client.get("/api/trash").json()
        group = next((item for item in trash["groups"] if item["id"] == "tasks"), None)
        if group:
            ids = [item["id"] for item in group["items"]]
            self.assertNotIn(old["id"], ids)
            self.assertIn(fresh["id"], ids)
        else:
            self.fail("группа задач пропала из корзины целиком")


if __name__ == "__main__":
    unittest.main()
