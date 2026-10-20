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

from app.core.config import ROOT  # noqa: E402
from app.main import app  # noqa: E402  (импорт поднимает init_db + seed)

client = TestClient(app)

# PWA-файлы живут в собранном frontend/dist; в CI бэкенда сборки нет —
# тогда роут раздачи не монтируется и тесты пропускаются.
DIST_READY = (ROOT / "frontend" / "dist" / "sw.js").is_file()

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

    def test_healthz_reports_build(self):
        # Сборка обязана представляться: это способ отличить свежий контейнер
        # от устаревшего (build поднимается в app/core/version.py каждым патчем).
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        build = response.json().get("build")
        self.assertTrue(build and str(build).strip(), "healthz не назвал сборку")

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


class HomeHubTest(unittest.TestCase):
    """Агрегат /api/home — основа хаба «Сегодня».

    Проверяем контракт: секции с флагами, проекты, и блок уведомлений,
    который регистрируется на мосту как home-блок (не через inbox —
    уведомления не делятся по проектам).
    """

    def setUp(self):
        _login()
        self._cleanup()

    def tearDown(self):
        self._cleanup()
        client.post("/api/auth/logout")
        client.cookies.clear()

    def _cleanup(self):
        from app.core.db import session_scope
        from app.core.models import User
        from app.modules.notifications.models import Notification
        from sqlalchemy import delete, select

        with session_scope() as db:
            user = db.scalars(select(User).where(User.username == "tester")).first()
            if user is not None:
                db.execute(delete(Notification).where(Notification.user_id == user.id))

    def test_home_shape_and_notifications_block(self):
        response = client.get("/api/home")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ("projects", "tasks", "mail", "events", "notifications", "sections"):
            self.assertIn(key, body)
        sections = body["sections"]
        for key in ("tasks", "mail", "events", "notifications"):
            self.assertIn(key, sections)
            self.assertIsInstance(sections[key], bool)

    def test_home_lists_user_notifications(self):
        from app.core.db import session_scope
        from app.core.models import User
        from app.modules.notifications.models import Notification
        from sqlalchemy import select

        with session_scope() as db:
            user = db.scalars(select(User).where(User.username == "tester")).first()
            db.add(
                Notification(
                    user_id=user.id,
                    event_type="task.deadline_soon",
                    title="Срок задачи близко",
                    body="Задача «Проверить патч»",
                    link="/projects/1/tasks/1",
                    show_browser=True,
                    read=False,
                )
            )

        response = client.get("/api/home")
        self.assertEqual(response.status_code, 200)
        notes = response.json()["notifications"]
        self.assertTrue(any("Срок задачи близко" in item["title"] for item in notes))
        item = next(item for item in notes if "Срок задачи близко" in item["title"])
        self.assertEqual(item["link"], "/projects/1/tasks/1")
        self.assertFalse(item["read"])
        # Лёгкая лента хаба не тянет доставки (тяжёлый _out не используется).
        self.assertNotIn("deliveries", item)

    def test_home_requires_auth(self):
        client.post("/api/auth/logout")
        client.cookies.clear()
        self.assertEqual(client.get("/api/home").status_code, 401)

    def test_home_tasks_carry_priority_and_offset_pages(self):
        """Патч N: приоритет в ленте, порядок «важное и горящее вверх» и
        task_offset для кнопки «Показать ещё»."""
        import uuid as _uuid

        mark = "prio" + _uuid.uuid4().hex[:6]
        created = client.post("/api/projects", json={"name": "Сегодня приоритеты " + mark}).json()
        project_id = created["id"]
        for title, priority in (
            ("Низкий " + mark, "low"),
            ("Высокий " + mark, "high"),
            ("Обычный " + mark, "normal"),
        ):
            response = client.post(
                f"/api/projects/{project_id}/tasks",
                json={"title": title, "deadline": "2026-10-01T09:00:00", "priority": priority},
            )
            assert response.status_code == 201, response.text

        body = client.get("/api/home").json()
        rows = [item for item in body["tasks"] if mark in item["title"]]
        self.assertTrue(rows, "задачи проекта не попали в /api/home")
        priorities = {item["title"].split()[0]: item["priority"] for item in rows}
        self.assertEqual(priorities["Высокий"], "high")
        self.assertEqual(priorities["Обычный"], "normal")
        self.assertEqual(priorities["Низкий"], "low")
        # Просроченные: сначала высокий приоритет, потом обычный, потом низкий.
        order = [item["title"].split()[0] for item in rows]
        self.assertEqual(order, ["Высокий", "Обычный", "Низкий"])

        # Пагинация: со сдвигом 1 прилетает хвост того же списка.
        paged = client.get("/api/home", params={"task_offset": 1}).json()
        rows_tail = [item for item in paged["tasks"] if mark in item["title"]]
        tail_order = [item["title"].split()[0] for item in rows_tail]
        self.assertEqual(tail_order, ["Обычный", "Низкий"])


@unittest.skipUnless(DIST_READY, "нужен собранный frontend/dist")
class PwaFilesTest(unittest.TestCase):
    """Раздача PWA-файлов: манифест, сервис-воркер, иконки.

    Тип содержимого и no-cache — часть контракта: SPA-заглушка с text/html
    вместо sw.js ломает установку PWA с криптичной ошибкой MIME.
    """

    def test_manifest_served_with_type(self):
        response = client.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/manifest+json", response.headers["content-type"])
        body = response.json()
        self.assertIn("icons", body)
        self.assertGreaterEqual(len(body["icons"]), 3)
        for icon in body["icons"]:
            self.assertIn("src", icon)

    def test_service_worker_no_cache(self):
        response = client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["content-type"])
        self.assertIn("no-cache", response.headers.get("cache-control", ""))

    def test_icons_served(self):
        for name in ("icon-192.png", "icon-512.png", "icon-512-maskable.png", "apple-touch-icon.png"):
            response = client.get("/icons/" + name)
            self.assertEqual(response.status_code, 200, name)
            self.assertIn("image/png", response.headers["content-type"], name)

    def test_spa_shell_revalidates(self):
        # После пересборки образа браузер обязан увидеть новую оболочку:
        # эвристический кеш index.html — источник «обновился, но ничего
        # не поменялось». no-cache оставляет ETag-ревалидацию (304).
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-cache", response.headers.get("cache-control", ""))

    def test_deep_route_serves_shell(self):
        # Глубокие маршруты SPA (например, глобальные секреты) отдают ту же
        # оболочку с той же политикой ревалидации.
        response = client.get("/secrets")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-cache", response.headers.get("cache-control", ""))

    def test_vite_assets_immutable(self):
        # Хешированные чанки неизменны: годовой immutable без ревалидации.
        assets_dir = ROOT / "frontend" / "dist" / "assets"
        hashed = next((item for item in sorted(assets_dir.iterdir()) if item.is_file()), None)
        self.assertIsNotNone(hashed, "в dist/assets нет файлов")
        response = client.get("/assets/" + hashed.name)
        self.assertEqual(response.status_code, 200)
        control = response.headers.get("cache-control", "")
        self.assertIn("immutable", control)
        self.assertIn("max-age=31536000", control)


if __name__ == "__main__":
    unittest.main()
