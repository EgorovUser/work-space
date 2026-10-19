"""HTTP-тесты через TestClient: логин, сессии, изоляция проектов, смена пароля.

Поднимает настоящее приложение (create_app при импорте app.main): те же
роутеры, зависимости и middleware, что и в проде. Lifespan (scheduler,
outbox) при TestClient без контекст-менеджера не стартует — джобы не мешают.

Инициализация идемпотентна: при `unittest discover` первым импортируется
test_app (готовит env и конфиг); при одиночном запуске конфиг поднимаем сами.
"""
from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-http-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "http-test-secret")
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

PASSWORD = "tester-pass"


def _login(password: str = PASSWORD, username: str = "tester"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _me():
    return client.get("/api/auth/me")


def _me_is_anonymous() -> bool:
    """/api/auth/me для анонима возвращает 200 + null (контракт фронта), не 401."""
    response = _me()
    return response.status_code == 200 and response.json() is None


def _me_user() -> dict | None:
    return _me().json()


class PublicRoutesTest(unittest.TestCase):
    def test_healthz_public(self):
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertIn("status", response.json())

    def test_unknown_api_route_404(self):
        self.assertEqual(client.get("/api/no-such-route").status_code, 404)


class AuthFlowTest(unittest.TestCase):
    def tearDown(self):
        client.post("/api/auth/logout")

    def test_login_wrong_password_401(self):
        self.assertEqual(_login(password="totally-wrong").status_code, 401)

    def test_login_unknown_user_401(self):
        self.assertEqual(_login(username="no-such-user").status_code, 401)

    def test_me_anonymous_without_session(self):
        client.cookies.clear()
        self.assertTrue(_me_is_anonymous())

    def test_login_me_logout_flow(self):
        response = _login()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["username"], "tester")
        self.assertIn("id", body)

        me = _me_user()
        self.assertIsNotNone(me)
        self.assertEqual(me["username"], "tester")

        logout = client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200)
        self.assertTrue(_me_is_anonymous())

        # Сессия на сервере действительно очищена: повторный логин работает
        self.assertEqual(_login().status_code, 200)
        self.assertIsNotNone(_me_user())


class RateLimitTest(unittest.TestCase):
    def test_too_many_failures_block_login(self):
        username = "ratelimit-probe"
        limit = 10  # auth.login_max_attempts по умолчанию
        for _ in range(limit):
            self.assertEqual(_login(username=username).status_code, 401)
        blocked = _login(username=username)
        self.assertEqual(blocked.status_code, 429)
        # Другой логин не задет: блокировка на пару (логин, IP)
        self.assertEqual(_login().status_code, 200)
        client.post("/api/auth/logout")


class ProjectIsolationTest(unittest.TestCase):
    def tearDown(self):
        client.post("/api/auth/logout")

    def test_projects_require_login(self):
        self.assertEqual(client.get("/api/projects").status_code, 401)

    def test_missing_project_404(self):
        _login()
        response = client.get("/api/projects/999999")
        self.assertEqual(response.status_code, 404)

    def test_create_and_get_project(self):
        _login()
        created = client.post("/api/projects", json={"name": "http-test-project"})
        self.assertEqual(created.status_code, 201)
        project_id = created.json()["id"]

        got = client.get(f"/api/projects/{project_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["name"], "http-test-project")

        listed = client.get("/api/projects")
        self.assertIn(project_id, [item["id"] for item in listed.json()["items"]])

    def test_create_project_validation(self):
        _login()
        self.assertEqual(client.post("/api/projects", json={}).status_code, 422)


class PasswordChangeTest(unittest.TestCase):
    NEW_PASSWORD = "another-long-password"

    def tearDown(self):
        # Возвращаем исходный пароль, чтобы другие тесты не зависели от порядка
        client.cookies.clear()
        _login(password=self.NEW_PASSWORD)
        client.post(
            "/api/auth/password",
            json={"old_password": self.NEW_PASSWORD, "new_password": PASSWORD},
        )
        client.post("/api/auth/logout")
        client.cookies.clear()

    def test_wrong_old_password_400(self):
        _login()
        response = client.post(
            "/api/auth/password",
            json={"old_password": "nope", "new_password": self.NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 400)

    def test_same_password_400(self):
        _login()
        response = client.post(
            "/api/auth/password",
            json={"old_password": PASSWORD, "new_password": PASSWORD},
        )
        self.assertEqual(response.status_code, 400)

    def test_short_password_400(self):
        _login()
        response = client.post(
            "/api/auth/password",
            json={"old_password": PASSWORD, "new_password": "short"},
        )
        self.assertEqual(response.status_code, 400)

    def test_change_invalidates_old_session_and_accepts_new_password(self):
        _login()
        response = client.post(
            "/api/auth/password",
            json={"old_password": PASSWORD, "new_password": self.NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)

        # Старая cookie больше не действует: session_version вырос,
        # me видит анонима (null) вместо пользователя
        self.assertTrue(_me_is_anonymous())

        # Новый пароль работает
        client.cookies.clear()
        again = _login(password=self.NEW_PASSWORD)
        self.assertEqual(again.status_code, 200)
        self.assertIsNotNone(_me_user())


if __name__ == "__main__":
    unittest.main()
