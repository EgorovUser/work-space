"""HTTP-тесты истории значений секрета (патч O): снимки при изменении
пароля/логина/ссылки, откат без разрушения, копирование прежнего значения,
подрезка глубины, поведение в корзине и при окончательном удалении.

Поднимает то же приложение, что и test_http.py; при `unittest discover`
первым импортируется test_app и готовит окружение, здесь остаётся только
поднять конфиг при одиночном запуске.
"""
from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-secret-history-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "secret-history-test-secret")
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
    body = {"title": title, "secret": "first-value", "username": "first-user", "url": "https://first.example"}
    body.update(extra)
    response = client.post(f"/api/projects/{project_id}/secrets", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _patch(project_id: int, secret_id: int, **fields) -> dict:
    response = client.patch(f"/api/projects/{project_id}/secrets/{secret_id}", json=fields)
    assert response.status_code == 200, response.text
    return response.json()


def _revisions(project_id: int, secret_id: int) -> list[dict]:
    response = client.get(f"/api/projects/{project_id}/secrets/{secret_id}/revisions")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _reveal(project_id: int, secret_id: int) -> str:
    response = client.post(f"/api/projects/{project_id}/secrets/{secret_id}/reveal")
    assert response.status_code == 200, response.text
    return response.json()["secret"]


class SecretHistoryAuthTest(unittest.TestCase):
    def test_anonymous_gets_401(self):
        client.post("/api/auth/logout")
        self.assertEqual(client.get("/api/projects/1/secrets/1/revisions").status_code, 401)
        self.assertEqual(client.post("/api/projects/1/secrets/1/revisions/1/reveal").status_code, 401)
        self.assertEqual(client.post("/api/projects/1/secrets/1/revisions/1/restore").status_code, 401)


class SecretHistoryTest(unittest.TestCase):
    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.mark = "hist" + str(id(self))[-6:]
        self.project = _project("История " + self.mark)
        self.secret = _secret(self.project["id"], "Учётка " + self.mark)

    def test_no_revisions_initially(self):
        self.assertEqual(_revisions(self.project["id"], self.secret["id"]), [])

    def test_update_creates_revision_with_changed_fields(self):
        payload = _patch(
            self.project["id"],
            self.secret["id"],
            secret="second-value",
            username="second-user",
            url="https://second.example",
            updated_at=self.secret["updated_at"],
        )
        self.assertIsNotNone(payload["revision_id"])
        items = _revisions(self.project["id"], self.secret["id"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], payload["revision_id"])
        # Различались все три важных поля — в фиксированном порядке.
        self.assertEqual(items[0]["changed"], ["secret", "username", "url"])
        self.assertTrue(items[0]["has_secret"])

    def test_revision_holds_previous_values(self):
        _patch(self.project["id"], self.secret["id"], secret="second-value", updated_at=self.secret["updated_at"])
        revision_id = _revisions(self.project["id"], self.secret["id"])[0]["id"]
        # Текущее значение — новое, в снимке — прежнее.
        self.assertEqual(_reveal(self.project["id"], self.secret["id"]), "second-value")
        response = client.post(
            f"/api/projects/{self.project['id']}/secrets/{self.secret['id']}/revisions/{revision_id}/reveal"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["secret"], "first-value")

    def test_restore_is_reversible(self):
        _patch(self.project["id"], self.secret["id"], secret="second-value", updated_at=self.secret["updated_at"])
        first = _revisions(self.project["id"], self.secret["id"])[0]
        response = client.post(
            f"/api/projects/{self.project['id']}/secrets/{self.secret['id']}/revisions/{first['id']}/restore"
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        # Откат сам сделал снимок — его можно вернуть обратно.
        self.assertIsNotNone(payload["revision_id"])
        self.assertEqual(_reveal(self.project["id"], self.secret["id"]), "first-value")
        items = _revisions(self.project["id"], self.secret["id"])
        self.assertEqual(len(items), 2)
        # Обратный откат возвращает второе значение.
        back = client.post(
            f"/api/projects/{self.project['id']}/secrets/{self.secret['id']}/revisions/{payload['revision_id']}/restore"
        )
        self.assertEqual(back.status_code, 200)
        self.assertEqual(_reveal(self.project["id"], self.secret["id"]), "second-value")

    def test_no_revision_without_real_change(self):
        # Правка только названия — история не растёт.
        payload = _patch(self.project["id"], self.secret["id"], title="Новое название " + self.mark, updated_at=self.secret["updated_at"])
        self.assertIsNone(payload["revision_id"])
        self.assertEqual(_revisions(self.project["id"], self.secret["id"]), [])
        # Те же значения важных полей — снимка тоже нет.
        payload = _patch(
            self.project["id"],
            self.secret["id"],
            username="first-user",
            url="https://first.example",
            updated_at=payload["updated_at"],
        )
        self.assertIsNone(payload["revision_id"])
        self.assertEqual(_revisions(self.project["id"], self.secret["id"]), [])

    def test_stale_version_conflict_leaves_no_revision(self):
        response = client.patch(
            f"/api/projects/{self.project['id']}/secrets/{self.secret['id']}",
            json={"secret": "second-value", "updated_at": "2000-01-01T00:00:00+00:00"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(_revisions(self.project["id"], self.secret["id"]), [])

    def test_keep_revisions_prunes_tail(self):
        client.put(
            "/api/settings",
            json={"module": "secrets", "key": "history.keep_revisions", "scope": "global", "value": 2},
        )
        try:
            version = self.secret["updated_at"]
            for index in range(4):
                payload = _patch(self.project["id"], self.secret["id"], secret="value-" + str(index), updated_at=version)
                version = payload["updated_at"]
            items = _revisions(self.project["id"], self.secret["id"])
            self.assertEqual(len(items), 2)
            # Остались самые свежие снимки.
            self.assertEqual(items[0]["id"], payload["revision_id"])
        finally:
            client.post(
                "/api/settings/reset",
                json={"module": "secrets", "key": "history.keep_revisions", "scope": "global"},
            )

    def test_wrong_revision_or_foreign_secret_404(self):
        other = _secret(self.project["id"], "Другая " + self.mark)
        _patch(self.project["id"], self.secret["id"], secret="second-value", updated_at=self.secret["updated_at"])
        revision_id = _revisions(self.project["id"], self.secret["id"])[0]["id"]
        base = f"/api/projects/{self.project['id']}/secrets"
        self.assertEqual(client.post(f"{base}/{other['id']}/revisions/{revision_id}/restore").status_code, 404)
        self.assertEqual(client.post(f"{base}/{other['id']}/revisions/{revision_id}/reveal").status_code, 404)
        self.assertEqual(client.post(f"{base}/{self.secret['id']}/revisions/999999/restore").status_code, 404)

    def test_trash_keeps_history_until_purge(self):
        _patch(self.project["id"], self.secret["id"], secret="second-value", updated_at=self.secret["updated_at"])
        secret_id = self.secret["id"]
        project_id = self.project["id"]
        client.delete(f"/api/projects/{project_id}/secrets/{secret_id}")
        # Секрет в корзине — история недоступна, но не потеряна.
        self.assertEqual(client.get(f"/api/projects/{project_id}/secrets/{secret_id}/revisions").status_code, 404)
        restored = client.post(f"/api/trash/secrets/{secret_id}/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(len(_revisions(project_id, secret_id)), 1)
        # Окончательное удаление выметает и снимки.
        client.delete(f"/api/projects/{project_id}/secrets/{secret_id}")
        purged = client.delete(f"/api/trash/secrets/{secret_id}")
        self.assertEqual(purged.status_code, 204, purged.text)
        from app.core.db import session_scope
        from sqlalchemy import select
        from app.modules.secrets.models import SecretRevision
        with session_scope() as session:
            left = list(session.scalars(select(SecretRevision).where(SecretRevision.secret_id == secret_id)).all())
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
