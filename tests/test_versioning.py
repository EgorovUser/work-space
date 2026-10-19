"""Оптимистичная блокировка документов, секретов и примеров.

PATCH со stale updated_at обязан давать 409 — иначе две открытые вкладки
затирают правки друг друга молча. Без updated_at поведение прежнее (200).
"""

from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-versioning-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "versioning-test-secret")
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


class VersioningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client.post("/api/auth/login", json={"username": "tester", "password": "tester-pass"})
        created = client.post("/api/projects", json={"name": "versioning-project"})
        cls.project_id = created.json()["id"]

    @classmethod
    def tearDownClass(cls):
        client.post("/api/auth/logout")

    def test_document_stale_version_409_and_fresh_200(self):
        made = client.post(
            f"/api/projects/{self.project_id}/documents",
            files={"file": ("notes.txt", b"versioning", "text/plain")},
            data={"title": "Документ конкуренции", "note": ""},
        )
        self.assertEqual(made.status_code, 201)
        doc_id = made.json()["id"]
        got = client.get(f"/api/projects/{self.project_id}/documents/{doc_id}")
        updated_at = got.json()["updated_at"]

        # Вкладка А сохранила правки — версия уехала.
        first = client.patch(
            f"/api/projects/{self.project_id}/documents/{doc_id}",
            json={"title": "Правка из вкладки А", "updated_at": updated_at},
        )
        self.assertEqual(first.status_code, 200)

        # Вкладка Б всё ещё держит старую версию — её должно отбить.
        stale = client.patch(
            f"/api/projects/{self.project_id}/documents/{doc_id}",
            json={"title": "Правка из вкладки Б", "updated_at": updated_at},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertIn("вкладке", stale.json()["detail"])

        # Без updated_at (старые клиенты, скрипты) — как раньше.
        legacy = client.patch(
            f"/api/projects/{self.project_id}/documents/{doc_id}",
            json={"title": "Правка без версии"},
        )
        self.assertEqual(legacy.status_code, 200)

        # Мусорная дата — понятная ошибка, не 500.
        garbage = client.patch(
            f"/api/projects/{self.project_id}/documents/{doc_id}",
            json={"title": "Правка", "updated_at": "не дата"},
        )
        self.assertEqual(garbage.status_code, 400)

    def test_secret_stale_version_409(self):
        made = client.post(
            f"/api/projects/{self.project_id}/secrets",
            json={"title": "Секрет конкуренции", "kind": "", "username": "", "url": "", "note": "", "secret": "s3cr3t"},
        )
        self.assertEqual(made.status_code, 201)
        secret_id = made.json()["id"]
        got = client.get(f"/api/projects/{self.project_id}/secrets/{secret_id}")
        updated_at = got.json()["updated_at"]

        first = client.patch(
            f"/api/projects/{self.project_id}/secrets/{secret_id}",
            json={"title": "Правка А", "updated_at": updated_at},
        )
        self.assertEqual(first.status_code, 200)

        stale = client.patch(
            f"/api/projects/{self.project_id}/secrets/{secret_id}",
            json={"title": "Правка Б", "updated_at": updated_at},
        )
        self.assertEqual(stale.status_code, 409)

    def test_example_stale_version_409(self):
        made = client.post(
            f"/api/projects/{self.project_id}/examples",
            json={"title": "Пример конкуренции", "body": "текст", "note": "", "language": "", "pinned": False, "tags": []},
        )
        self.assertEqual(made.status_code, 201)
        example_id = made.json()["id"]
        got = client.get(f"/api/projects/{self.project_id}/examples/{example_id}")
        updated_at = got.json()["updated_at"]

        first = client.patch(
            f"/api/projects/{self.project_id}/examples/{example_id}",
            json={"title": "Правка А", "updated_at": updated_at},
        )
        self.assertEqual(first.status_code, 200)

        stale = client.patch(
            f"/api/projects/{self.project_id}/examples/{example_id}",
            json={"title": "Правка Б", "updated_at": updated_at},
        )
        self.assertEqual(stale.status_code, 409)
