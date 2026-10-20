"""HTTP-тесты RDP-подключений (/api/projects/{id}/rdp) и генерации .rdp.

Поднимает то же приложение, что и test_http.py; при `unittest discover`
первым импортируется test_app и готовит окружение, здесь остаётся только
поднять конфиг при одиночном запуске.
"""
from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-rdp-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "rdp-test-secret")
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


def _rdp(project_id: int, name: str, host: str, **extra) -> dict:
    body = {"name": name, "host": host}
    body.update(extra)
    response = client.post(f"/api/projects/{project_id}/rdp", json=body)
    assert response.status_code == 201, response.text
    return response.json()


class RdpAuthTest(unittest.TestCase):
    def test_anonymous_gets_401(self):
        client.post("/api/auth/logout")
        project = None
        self.assertEqual(client.get("/api/projects/1/rdp").status_code, 401)
        self.assertEqual(client.post("/api/projects/1/rdp", json={"name": "x", "host": "h"}).status_code, 401)
        self.assertEqual(client.get("/api/projects/1/rdp/1/file").status_code, 401)
        self.assertIsNone(project)


class RdpCrudTest(unittest.TestCase):
    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.mark = "rdp" + str(id(self))[-6:]
        self.project = _project("Серверы " + self.mark)
        self.other = _project("Чужой " + self.mark)

    def test_create_defaults_and_fields(self):
        created = _rdp(self.project["id"], "Сервер отчётов " + self.mark, "10.0.0.7", username="admin", domain="CORP", note="Бухгалтерия")
        self.assertEqual(created["port"], 3389)
        self.assertEqual(created["host"], "10.0.0.7")
        self.assertEqual(created["username"], "admin")
        self.assertEqual(created["domain"], "CORP")
        self.assertEqual(created["note"], "Бухгалтерия")
        self.assertFalse(created["archived"])

        custom = _rdp(self.project["id"], "Шлюз " + self.mark, "gw.corp.local", port=3390)
        self.assertEqual(custom["port"], 3390)

        payload = client.get(f"/api/projects/{self.project['id']}/rdp").json()
        names = [item["name"] for item in payload["items"]]
        self.assertIn("Сервер отчётов " + self.mark, names)
        self.assertIn("Шлюз " + self.mark, names)

    def test_filter_by_name_and_host(self):
        _rdp(self.project["id"], "Игла " + self.mark, "10.1.2.3")
        _rdp(self.project["id"], "Стог " + self.mark, "10.9.9.9")
        by_name = client.get(f"/api/projects/{self.project['id']}/rdp", params={"q": "игла"}).json()
        self.assertEqual([item["name"] for item in by_name["items"]], ["Игла " + self.mark])
        by_host = client.get(f"/api/projects/{self.project['id']}/rdp", params={"q": "10.1.2.3"}).json()
        self.assertEqual([item["name"] for item in by_host["items"]], ["Игла " + self.mark])

    def test_validation_errors(self):
        base = f"/api/projects/{self.project['id']}/rdp"
        cases = (
            ({"name": "", "host": "10.0.0.1"}, "название"),
            ({"name": "Без адреса", "host": " "}, "адрес"),
            ({"name": "С пробелом", "host": "10.0.0.1 7"}, "пробел"),
            ({"name": "С двоеточием", "host": "10.0.0.1:3390"}, "двоеточ"),
            ({"name": "Порт", "host": "10.0.0.1", "port": 0}, "Порт"),
            ({"name": "Порт", "host": "10.0.0.1", "port": 70000}, "Порт"),
            ({"name": "Длина", "host": "10.0.0." + "1" * 300}, "длиннее"),
        )
        for body, needle in cases:
            response = client.post(base, json=body)
            self.assertEqual(response.status_code, 400, body)
            self.assertIn(needle, response.json()["detail"])

    def test_project_isolation(self):
        created = _rdp(self.project["id"], "Только здесь " + self.mark, "10.0.0.7")
        self.assertEqual(client.get(f"/api/projects/{self.other['id']}/rdp/{created['id']}").status_code, 404)
        self.assertEqual(client.get(f"/api/projects/{self.other['id']}/rdp/{created['id']}/file").status_code, 404)
        payload = client.get(f"/api/projects/{self.other['id']}/rdp").json()
        self.assertEqual(payload["items"], [])

    def test_patch_archive_and_version_conflict(self):
        created = _rdp(self.project["id"], "Конфликт " + self.mark, "10.0.0.7")
        base = f"/api/projects/{self.project['id']}/rdp/{created['id']}"

        renamed = client.patch(base, json={"name": "Переименован " + self.mark, "host": "10.0.0.8"})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["host"], "10.0.0.8")

        stale = client.patch(base, json={"name": "Старая версия", "updated_at": created["updated_at"]})
        self.assertEqual(stale.status_code, 409)

        archived = client.patch(base, json={"archived": True})
        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.json()["archived"])
        self.assertEqual(client.get(f"/api/projects/{self.project['id']}/rdp").json()["items"], [])
        restored = client.get(f"/api/projects/{self.project['id']}/rdp", params={"include_archived": "true"}).json()
        self.assertEqual([item["name"] for item in restored["items"]], ["Переименован " + self.mark])

    def test_delete(self):
        created = _rdp(self.project["id"], "Удалить " + self.mark, "10.0.0.7")
        base = f"/api/projects/{self.project['id']}/rdp/{created['id']}"
        self.assertEqual(client.delete(base).status_code, 204)
        self.assertEqual(client.get(base).status_code, 404)
        self.assertEqual(client.get(base + "/file").status_code, 404)


class RdpFileTest(unittest.TestCase):
    """Файл .rdp: содержимое без пароля и честные заголовки скачивания."""

    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.mark = "файл" + str(id(self))[-6:]
        self.project = _project("Файлы " + self.mark)

    def test_file_with_custom_port_and_credentials(self):
        created = _rdp(self.project["id"], "Файловый " + self.mark, "files.corp.local", port=3390, username="corp\\admin", domain="CORP")
        response = client.get(f"/api/projects/{self.project['id']}/rdp/{created['id']}/file")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/x-rdp", response.headers["content-type"])
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertTrue(response.headers["content-disposition"].endswith(".rdp\""))
        self.assertIn("no-store", response.headers.get("cache-control", ""))

        body = response.text
        self.assertIn("full address:s:files.corp.local:3390", body)
        self.assertIn("username:s:corp\\admin", body)
        self.assertIn("domain:s:CORP", body)
        self.assertIn("prompt for credentials:i:1", body)
        self.assertNotIn("password", body.lower())
        self.assertNotIn("pwd key", body.lower())

    def test_file_with_standard_port_omits_it(self):
        created = _rdp(self.project["id"], "Стандарт " + self.mark, "std.corp.local")
        body = client.get(f"/api/projects/{self.project['id']}/rdp/{created['id']}/file").text
        self.assertIn("full address:s:std.corp.local\r\n", body)
        self.assertNotIn("std.corp.local:3389", body)

    def test_filename_is_ascii_safe(self):
        created = _rdp(self.project["id"], "Файловый сервер №1/тест " + self.mark, "win.local")
        disposition = client.get(f"/api/projects/{self.project['id']}/rdp/{created['id']}/file").headers["content-disposition"]
        # Кириллица и слэши не должны попасть в filename: ломают заголовок.
        for char in "№/тест":
            self.assertNotIn(char, disposition)
        self.assertTrue(disposition.endswith(".rdp\""))


class RdpSearchTest(unittest.TestCase):
    """Поисковый провайдер моста: ищет по названию и по адресу."""

    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.mark = "поиск" + str(id(self))[-6:]
        self.project = _project("Поиск RDP " + self.mark)
        _rdp(self.project["id"], "Игла " + self.mark, "10.7.7.7")
        _rdp(self.project["id"], "Стог " + self.mark, "10.8.8.8")

    def _provider(self, query: str) -> list[str]:
        from app.core.db import session_scope
        from app.modules.rdp import service

        with session_scope() as session:
            found = service.search_provider(session, self.project["id"], None, query, 5)
            return [item["title"] for item in found]

    def test_finds_by_name(self):
        self.assertEqual(self._provider("игла " + self.mark), ["Игла " + self.mark])

    def test_finds_by_host(self):
        self.assertEqual(self._provider("10.8.8.8"), ["Стог " + self.mark])

    def test_global_fts_index_covers_rdp(self):
        # Общий поиск (/api/search) гоняет FTS5: rdp_connections проиндексирован
        # ensure_search_index, и сервер находится по адресу.
        response = client.get("/api/search", params={"q": "10.7.7.7"})
        self.assertEqual(response.status_code, 200)
        groups = response.json()["groups"]
        rdp_group = next((group for group in groups if group["id"] == "rdp"), None)
        self.assertIsNotNone(rdp_group, "RDP-группа не вернулась из общего поиска")
        titles = [item["title"] for item in rdp_group["items"]]
        self.assertIn("Игла " + self.mark, titles)


class RdpSecretLinkTest(unittest.TestCase):
    """Связка подключения с секретом (патч N): валидация и подтяжка логина."""

    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.mark = "sec" + str(id(self))[-6:]
        self.project = _project("RDP секреты " + self.mark)
        self.other = _project("Чужой секрет " + self.mark)
        response = client.post(
            f"/api/projects/{self.project['id']}/secrets",
            json={"title": "Учётка сервера " + self.mark, "secret": "pass-" + self.mark, "username": "corp-admin"},
        )
        assert response.status_code == 201, response.text
        self.secret = response.json()

    def test_link_and_title_in_list(self):
        created = _rdp(self.project["id"], "С секретом " + self.mark, "10.0.0.9", secret_id=self.secret["id"])
        self.assertEqual(created["secret_id"], self.secret["id"])
        self.assertEqual(created["secret_title"], "Учётка сервера " + self.mark)
        payload = client.get(f"/api/projects/{self.project['id']}/rdp").json()
        row = next(item for item in payload["items"] if item["id"] == created["id"])
        self.assertEqual(row["secret_title"], "Учётка сервера " + self.mark)

    def test_foreign_or_wrong_secret_rejected(self):
        response = client.post(
            f"/api/projects/{self.project['id']}/rdp",
            json={"name": "Чужой " + self.mark, "host": "10.0.0.9", "secret_id": 999999},
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("Секрет не найден", body["detail"])

    def test_secret_from_other_project_rejected(self):
        response = client.post(
            f"/api/projects/{self.other['id']}/secrets",
            json={"title": "Не тот проект " + self.mark, "secret": "x", "username": "x"},
        )
        other_secret = response.json()
        response = client.post(
            f"/api/projects/{self.project['id']}/rdp",
            json={"name": "Подмена " + self.mark, "host": "10.0.0.9", "secret_id": other_secret["id"]},
        )
        self.assertEqual(response.status_code, 400)

    def test_clear_link_with_null(self):
        created = _rdp(self.project["id"], "Очистка " + self.mark, "10.0.0.9", secret_id=self.secret["id"])
        response = client.patch(
            f"/api/projects/{self.project['id']}/rdp/{created['id']}",
            json={"secret_id": None, "updated_at": created["updated_at"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["secret_id"])

    def test_file_pulls_username_from_secret(self):
        created = _rdp(self.project["id"], "Без логина " + self.mark, "10.0.0.9", secret_id=self.secret["id"])
        body = client.get(f"/api/projects/{self.project['id']}/rdp/{created['id']}/file").text
        self.assertIn("username:s:corp-admin", body)
        self.assertNotIn("pass-" + self.mark, body)

    def test_manual_username_wins(self):
        created = _rdp(
            self.project["id"], "Свой логин " + self.mark, "10.0.0.9",
            username="local-admin", secret_id=self.secret["id"],
        )
        body = client.get(f"/api/projects/{self.project['id']}/rdp/{created['id']}/file").text
        self.assertIn("username:s:local-admin", body)
        self.assertNotIn("corp-admin", body)


class RdpPingTest(unittest.TestCase):
    """TCP-пинг: форма ответа и обе ветки результата, без сети."""

    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.mark = "ping" + str(id(self))[-6:]
        self.project = _project("RDP пинг " + self.mark)
        self.row = _rdp(self.project["id"], "Пингуемый " + self.mark, "10.0.0.7")

    def test_anonymous_gets_401(self):
        client.post("/api/auth/logout")
        self.assertEqual(client.post(f"/api/projects/{self.project['id']}/rdp/{self.row['id']}/ping").status_code, 401)

    def test_unknown_connection_404(self):
        self.assertEqual(client.post(f"/api/projects/{self.project['id']}/rdp/999999/ping").status_code, 404)

    def test_ok_shape(self):
        from unittest.mock import patch

        class _Sock:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("app.modules.rdp.service.socket.create_connection", return_value=_Sock()):
            payload = client.post(f"/api/projects/{self.project['id']}/rdp/{self.row['id']}/ping").json()
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["latency_ms"], int)
        self.assertEqual(payload["error"], "")

    def test_failure_shape(self):
        from unittest.mock import patch

        with patch(
            "app.modules.rdp.service.socket.create_connection",
            side_effect=OSError("нет маршрута к хосту"),
        ):
            payload = client.post(f"/api/projects/{self.project['id']}/rdp/{self.row['id']}/ping").json()
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["latency_ms"])
        self.assertIn("нет маршрута", payload["error"])


if __name__ == "__main__":
    unittest.main()
