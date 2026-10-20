"""Глобальный поиск: FTS5-индекс, живая синхронизация триггерами, приватность секретов.

Ключевые инварианты:
- контент находится по префиксу слова («уникум» найдёт «уникумный»);
- правка и удаление отражаются в индексе сразу (триггеры);
- зашифрованные поля секретов (note_enc и пр.) в индекс не попадают;
- мусорный поисковый запрос не даёт 500;
- аноним получает 401.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone

_root = tempfile.mkdtemp(prefix="ws-search-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "search-test-secret")
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


def _word() -> str:
    return "уникум" + uuid.uuid4().hex[:8]


def _group_ids(payload: dict) -> set:
    return {group["id"] for group in payload["groups"]}


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client.post("/api/auth/login", json={"username": "tester", "password": "tester-pass"})
        created = client.post("/api/projects", json={"name": "поиск-проект"})
        cls.project_id = created.json()["id"]

    @classmethod
    def tearDownClass(cls):
        client.post("/api/auth/logout")

    def test_finds_tasks_notes_documents_examples_secrets_and_mail(self):
        word = _word()
        client.post(
            f"/api/projects/{self.project_id}/tasks",
            json={"title": f"Задача {word}", "description": "описание"},
        )
        client.post(f"/api/projects/{self.project_id}/notes", json={"body": f"заметка про {word}"})
        client.post(
            f"/api/projects/{self.project_id}/documents",
            files={"file": ("doc.txt", b"content", "text/plain")},
            data={"title": f"Документ {word}", "note": ""},
        )
        client.post(
            f"/api/projects/{self.project_id}/examples",
            json={"title": f"Пример {word}", "body": "текст", "note": "", "language": "", "pinned": False, "tags": []},
        )
        client.post(
            f"/api/projects/{self.project_id}/secrets",
            json={"title": f"Секрет {word}", "kind": "", "username": "", "url": "", "note": "", "secret": "s3cr3t"},
        )

        from app.core.db import session_scope
        from app.modules.mail.models import MailMessage

        with session_scope() as session:
            session.add(
                MailMessage(
                    project_id=self.project_id,
                    subject=f"Письмо {word}",
                    body=f"тело письма {word}",
                    from_name="Поиск Тестов",
                    from_addr="search@example.com",
                    received_at=datetime.now(timezone.utc),
                )
            )

        response = client.get("/api/search", params={"q": word})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        found = _group_ids(payload)
        self.assertEqual(
            found,
            {"tasks", "notes", "documents", "examples", "secrets", "mail"},
            f"ожидали все группы, нашли: {found}; payload={payload}",
        )
        # Сниппеты подсветки приходят с маркерами \x01/\x02 вокруг совпадения.
        task_group = next(g for g in payload["groups"] if g["id"] == "tasks")
        self.assertIn("\x01", task_group["items"][0]["snippet"])
        self.assertEqual(task_group["items"][0]["project_id"], self.project_id)

    def test_prefix_match_finds_word_forms(self):
        word = _word()
        client.post(f"/api/projects/{self.project_id}/tasks", json={"title": f"Планировщик {word}ный"})

        response = client.get("/api/search", params={"q": word})
        self.assertEqual(response.status_code, 200)
        self.assertIn("tasks", _group_ids(response.json()))

    def test_edit_and_delete_reflected_in_index(self):
        old_word, new_word = _word(), _word()
        made = client.post(
            f"/api/projects/{self.project_id}/tasks",
            json={"title": f"Старое {old_word}"},
        ).json()
        task_id = made["id"]
        note = client.post(
            f"/api/projects/{self.project_id}/notes",
            json={"body": f"заметка {old_word}"},
        ).json()
        note_id = note["id"]

        self.assertIn("tasks", _group_ids(client.get("/api/search", params={"q": old_word}).json()))
        self.assertIn("notes", _group_ids(client.get("/api/search", params={"q": old_word}).json()))

        client.patch(
            f"/api/projects/{self.project_id}/tasks/{task_id}",
            json={"title": f"Новое {new_word}"},
        )
        self.assertNotIn("tasks", _group_ids(client.get("/api/search", params={"q": old_word}).json()))
        self.assertIn("tasks", _group_ids(client.get("/api/search", params={"q": new_word}).json()))

        client.delete(f"/api/projects/{self.project_id}/notes/{note_id}")
        self.assertNotIn("notes", _group_ids(client.get("/api/search", params={"q": old_word}).json()))

    def test_secret_encrypted_fields_are_not_indexed(self):
        word = _word()
        client.post(
            f"/api/projects/{self.project_id}/secrets",
            json={"title": "Обычный заголовок", "kind": "", "username": "", "url": "", "note": f"примечание {word}", "secret": word},
        )
        # Ни примечание, ни сам секрет не должны находиться — только заголовок.
        response = client.get("/api/search", params={"q": word})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("secrets", _group_ids(response.json()))

    def test_garbage_query_is_not_a_500(self):
        for garbage in ('"" AND', "(", '"незакрытая', "OR AND NOT", "   "):
            response = client.get("/api/search", params={"q": garbage})
            self.assertEqual(response.status_code, 200, f"мусорный запрос {garbage!r} уронил поиск")
            self.assertEqual(response.json()["groups"], [])

    def test_requires_auth(self):
        anonymous = TestClient(app)
        response = anonymous.get("/api/search", params={"q": "что угодно"})
        self.assertEqual(response.status_code, 401)

    def test_types_filter_limits_groups(self):
        # Палитра (патч N): фильтр по типам оставляет только выбранные
        # источники; неизвестные типы молча отбрасываются.
        word = _word()
        client.post(
            f"/api/projects/{self.project_id}/tasks",
            json={"title": f"Задача для фильтра {word}"},
        )
        client.post(
            f"/api/projects/{self.project_id}/documents",
            files={"file": ("doc.txt", b"content", "text/plain")},
            data={"title": f"Документ для фильтра {word}", "note": ""},
        )
        response = client.get("/api/search", params={"q": word, "types": "tasks"})
        self.assertEqual(_group_ids(response.json()), {"tasks"})
        response = client.get("/api/search", params={"q": word, "types": "tasks,secrets,nosuchthing"})
        self.assertEqual(_group_ids(response.json()), {"tasks"})
        # Пустой фильтр — все источники (задача и документ одновременно).
        response = client.get("/api/search", params={"q": word})
        self.assertIn("tasks", _group_ids(response.json()))
        self.assertIn("documents", _group_ids(response.json()))

    def test_trashed_rows_are_excluded(self):
        word = _word()
        created = client.post(
            f"/api/projects/{self.project_id}/tasks",
            json={"title": f"В корзину поиска {word}"},
        ).json()
        self.assertIn("tasks", _group_ids(client.get("/api/search", params={"q": word}).json()))
        client.delete(f"/api/projects/{self.project_id}/tasks/{created['id']}")
        self.assertNotIn("tasks", _group_ids(client.get("/api/search", params={"q": word}).json()))

    def test_short_query_returns_no_groups(self):
        response = client.get("/api/search", params={"q": "я"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["groups"], [])


if __name__ == "__main__":
    unittest.main()
