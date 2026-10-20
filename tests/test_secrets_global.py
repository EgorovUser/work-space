"""HTTP-тесты глобального раздела «Секреты» (/api/secrets) и настроек
дефолтного дедлайна (tasks.deadlines.default_days, secrets.list.global_limit).

Поднимает то же приложение, что и test_http.py; при `unittest discover`
первым импортируется test_app и готовит окружение, здесь остаётся только
поднять конфиг при одиночном запуске.
"""
from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-secrets-global-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "secrets-global-test-secret")
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


def _project(name: str) -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _secret(project_id: int, title: str, **extra) -> dict:
    body = {"title": title, "kind": "password", "secret": "value-" + title}
    body.update(extra)
    response = client.post(f"/api/projects/{project_id}/secrets", json=body)
    assert response.status_code == 201, response.text
    return response.json()


class GlobalSecretsAuthTest(unittest.TestCase):
    def test_anonymous_gets_401(self):
        client.post("/api/auth/logout")
        self.assertEqual(client.get("/api/secrets").status_code, 401)


class GlobalSecretsListTest(unittest.TestCase):
    """Группировка, поиск, архив и маскировка значений."""

    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.mark = "глб" + str(id(self))[-6:]
        self.first = _project("Альфа " + self.mark)
        self.second = _project("Бета " + self.mark)
        self.secret_a = _secret(
            self.first["id"],
            "Ключ альфа " + self.mark,
            username="alpha-user",
            url="https://alpha.example",
        )
        self.secret_b = _secret(self.second["id"], "Токен бета " + self.mark)

    def _titles(self, payload: dict) -> list[str]:
        return [item["title"] for group in payload["groups"] for item in group["items"]]

    def test_groups_by_project_with_names(self):
        payload = client.get("/api/secrets").json()
        names = [group["project_name"] for group in payload["groups"]]
        self.assertIn("Альфа " + self.mark, names)
        self.assertIn("Бета " + self.mark, names)
        # Группа отвечает за свой проект: чужих секретов в ней нет.
        for group in payload["groups"]:
            if group["project_name"] == "Альфа " + self.mark:
                self.assertEqual([item["title"] for item in group["items"]], ["Ключ альфа " + self.mark])
                self.assertEqual(group["project_id"], self.first["id"])

    def test_values_are_masked(self):
        payload = client.get("/api/secrets").json()
        for group in payload["groups"]:
            for item in group["items"]:
                self.assertNotIn("secret", item)
                self.assertNotIn("username", item)
                self.assertNotIn("url", item)
                self.assertNotIn("note", item)
                self.assertIn("has_secret", item)
                self.assertIn("has_username", item)

    def test_search_filters_by_title(self):
        payload = client.get("/api/secrets", params={"q": "токен бета " + self.mark}).json()
        titles = self._titles(payload)
        self.assertIn("Токен бета " + self.mark, titles)
        self.assertNotIn("Ключ альфа " + self.mark, titles)

    def test_archived_secret_hidden_unless_requested(self):
        response = client.patch(
            f"/api/projects/{self.second['id']}/secrets/{self.secret_b['id']}",
            json={"archived": True},
        )
        self.assertEqual(response.status_code, 200)

        default_view = client.get("/api/secrets").json()
        self.assertNotIn("Токен бета " + self.mark, self._titles(default_view))

        with_archive = client.get("/api/secrets", params={"include_archived": "true"}).json()
        self.assertIn("Токен бета " + self.mark, self._titles(with_archive))

    def test_archived_project_hidden_unless_requested(self):
        response = client.post(f"/api/projects/{self.second['id']}/archive", json={"archived": True})
        self.assertIn(response.status_code, (200, 204))

        default_view = client.get("/api/secrets").json()
        names = [group["project_name"] for group in default_view["groups"]]
        self.assertNotIn("Бета " + self.mark, names)

        with_archive = client.get("/api/secrets", params={"include_archived": "true"}).json()
        names = [group["project_name"] for group in with_archive["groups"]]
        self.assertIn("Бета " + self.mark, names)
        for group in with_archive["groups"]:
            if group["project_name"] == "Бета " + self.mark:
                self.assertTrue(group["project_archived"])


class GlobalSecretsLimitTest(unittest.TestCase):
    def test_global_limit_truncates(self):
        client.post("/api/auth/logout")
        _login()
        mark = "лим" + str(id(self))[-6:]
        project = _project("Лимит " + mark)
        _secret(project["id"], "Первый " + mark)
        _secret(project["id"], "Второй " + mark)

        client.put(
            "/api/settings",
            json={"module": "secrets", "key": "list.global_limit", "scope": "global", "value": 1},
        )
        try:
            payload = client.get("/api/secrets").json()
            # Потолок режет и список, и говорит об этом флагом.
            self.assertEqual(payload["total"], 1)
            self.assertTrue(payload["truncated"])
            titles = [item["title"] for group in payload["groups"] for item in group["items"]]
            self.assertEqual(len(titles), 1)
        finally:
            client.post(
                "/api/settings/reset",
                json={"module": "secrets", "key": "list.global_limit", "scope": "global"},
            )
        payload = client.get("/api/secrets").json()
        self.assertFalse(payload["truncated"])


class DefaultDeadlineSettingTest(unittest.TestCase):
    def test_defaults_are_visible_in_effective_settings(self):
        client.post("/api/auth/logout")
        _login()
        payload = client.get("/api/settings/effective").json()
        self.assertEqual(payload["tasks"]["deadlines.default_days"], 7)
        self.assertEqual(payload["secrets"]["list.global_limit"], 300)

    def test_setting_is_global_scope_only(self):
        client.post("/api/auth/logout")
        _login()
        response = client.put(
            "/api/settings",
            json={
                "module": "tasks",
                "key": "deadlines.default_days",
                "scope": "project",
                "project_id": 1,
                "value": 3,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_setting_rejects_out_of_range(self):
        client.post("/api/auth/logout")
        _login()
        response = client.put(
            "/api/settings",
            json={"module": "tasks", "key": "deadlines.default_days", "scope": "global", "value": -1},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
