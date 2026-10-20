"""Хаб счётчиков (патч T): /api/counters, кеш с TTL и сброс на мутациях.

Инварианты:
- эндпоинт закрыт входом;
- глобальный блок (почта, уведомления, корзина, секреты) всегда на месте;
- проектный блок считает активное: документы/примеры/секреты/RDP/заметки
  и непрочитанные письма по правилам проекта;
- кеш честный: мутация через API сбрасывает его сразу, а правка базы мимо
  API видна только после force (или истечения TTL) — это осознанный размен.
"""
from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-counters-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "counters-test-secret")
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

from app.core import counters  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

PASSWORD = "tester-pass"
MARK = "cnt" + os.urandom(4).hex()


def _login() -> None:
    client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})


def _project(name: str) -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _eml(subject: str, sender: str) -> bytes:
    headers = [
        "From: " + sender,
        "To: me@example.com",
        "Subject: " + subject,
        "Content-Type: text/plain; charset=utf-8",
        "",
        "Тело письма " + MARK,
        "",
    ]
    return ("\r\n".join(headers)).encode("utf-8")


class CountersApiTest(unittest.TestCase):
    def tearDown(self):
        client.post("/api/auth/logout")

    def test_requires_login(self):
        self.assertEqual(client.get("/api/counters").status_code, 401)

    def test_provider_registry_filled(self):
        # Все модули зарегистрировали своих провайдеров (патч AA): забыть
        # регистрацию — и бейдж молча опустеет, поэтому проверяем реестр.
        from app.core import counters

        self.assertEqual(
            sorted(counters._global_providers.keys()),
            ["mail", "notifications", "secrets", "trash"],
        )
        self.assertEqual(
            sorted(counters._project_providers.keys()),
            ["documents", "examples", "mail", "projects", "rdp", "secrets"],
        )

    def test_global_block_present(self):
        _login()
        response = client.get("/api/counters")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        for key in ("mail_unread", "notifications_unread", "trash_total", "secrets_total"):
            self.assertIsInstance(data.get(key), int, key)

    def test_project_block_counts_active(self):
        _login()
        project = _project("Счётчики " + MARK)
        pid = project["id"]

        # Правило раскладки + письмо от нужного отправителя: непрочитанное
        # письмо проекта попадает в счётчик почты.
        rule = client.post(
            f"/api/projects/{pid}/mail/rules",
            json={"name": "Отправитель", "field": "from", "op": "contains", "value": "corp.example", "action": "keep"},
        )
        self.assertEqual(rule.status_code, 201, rule.text)
        imported = client.post(
            f"/api/projects/{pid}/mail/import",
            files={"file": ("letter.eml", _eml("Счёт " + MARK, "billing@corp.example"), "message/rfc822")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual(imported.json()["status"], "stored")

        # Документ, пример, секрет, заметка, RDP.
        uploaded = client.post(
            f"/api/projects/{pid}/documents",
            files={"file": ("note-" + MARK + ".txt", ("документ " + MARK).encode(), "text/plain")},
            data={"title": "Документ " + MARK, "note": ""},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        example = client.post(
            f"/api/projects/{pid}/examples",
            json={"title": "Пример " + MARK, "body": "x", "note": "", "language": "other", "pinned": False, "tags": []},
        )
        self.assertEqual(example.status_code, 201, example.text)
        secret = client.post(
            f"/api/projects/{pid}/secrets",
            json={"title": "Секрет " + MARK, "kind": "", "username": "", "url": "", "note": "", "secret": "s3cr3t-" + MARK},
        )
        self.assertEqual(secret.status_code, 201, secret.text)
        note = client.post(f"/api/projects/{pid}/notes", json={"body": "Заметка " + MARK})
        self.assertEqual(note.status_code, 201, note.text)
        rdp = client.post(
            f"/api/projects/{pid}/rdp",
            json={"name": "RDP " + MARK, "host": "10.0.0." + MARK[-2:], "port": 3389, "username": "admin", "domain": "", "note": ""},
        )
        self.assertEqual(rdp.status_code, 201, rdp.text)

        response = client.get(f"/api/counters?project_id={pid}")
        self.assertEqual(response.status_code, 200, response.text)
        block = response.json()["project"]
        self.assertEqual(block["documents"], 1)
        self.assertEqual(block["examples"], 1)
        self.assertEqual(block["secrets"], 1)
        self.assertEqual(block["notes"], 1)
        self.assertEqual(block["rdp"], 1)
        self.assertEqual(block["mail"], 1)

        # Архив скрывает из счётчика: списки показывают только активное.
        patched = client.patch(f"/api/projects/{pid}/secrets/{secret.json()['id']}", json={"archived": True, "updated_at": secret.json()["updated_at"]})
        self.assertEqual(patched.status_code, 200, patched.text)
        block = client.get(f"/api/counters?project_id={pid}").json()["project"]
        self.assertEqual(block["secrets"], 0)
        self.assertEqual(block["documents"], 1)

    def test_trash_total_follows_mutation(self):
        _login()
        project = _project("Корзина " + MARK)
        pid = project["id"]
        secret = client.post(
            f"/api/projects/{pid}/secrets",
            json={"title": "В корзину " + MARK, "kind": "", "username": "", "url": "", "note": "", "secret": "x"},
        ).json()
        before = client.get("/api/counters").json()["trash_total"]

        deleted = client.delete(f"/api/projects/{pid}/secrets/{secret['id']}")
        self.assertEqual(deleted.status_code, 204, deleted.text)
        after = client.get("/api/counters").json()["trash_total"]
        self.assertEqual(after, before + 1, "мутация должна сбрасывать кеш счётчиков")


class CountersCacheTest(unittest.TestCase):
    """Кеш считает честно: мимо API меняется база — кеш не врёт дольше TTL."""

    def test_cached_then_force(self):
        _login()
        from app.modules.secrets.models import Secret

        state = counters.user_state(1, force=True)
        base = state.get("secrets_total", 0)

        # Правка базы напрямую, мимо API: кеш обязан отдать прежнее число,
        # force=True — свежее.
        from app.core.db import SessionLocal

        with SessionLocal() as session:
            row = Secret(
                project_id=1,
                title="прямой доступ " + MARK,
                kind="",
                username_enc="",
                url_enc="",
                note_enc="",
                secret_enc="",
                archived=False,
                deleted_at=None,
            )
            session.add(row)
            session.commit()

        try:
            cached = counters.user_state(1)
            self.assertEqual(cached.get("secrets_total", 0), base, "кеш не должен видеть правки мимо API")
            fresh = counters.user_state(1, force=True)
            self.assertEqual(fresh["secrets_total"], base + 1)
            # После force кеш прогрет: обычное чтение отдаёт свежее число.
            self.assertEqual(counters.user_state(1)["secrets_total"], base + 1)
        finally:
            with SessionLocal() as session:
                from sqlalchemy import delete

                session.execute(delete(Secret).where(Secret.title == "прямой доступ " + MARK))
                session.commit()
            counters.invalidate()

    def test_invalidate_clears_project_cache(self):
        _login()
        project = _project("Кеш проекта " + MARK)
        pid = project["id"]
        first = counters.project_counts(pid, force=True)
        self.assertEqual(first.get("documents", 0), 0)

        uploaded = client.post(
            f"/api/projects/{pid}/documents",
            files={"file": ("cached-" + MARK + ".txt", ("текст").encode(), "text/plain")},
            data={"title": "Кеш " + MARK, "note": ""},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)

        # Мутация через API сбросила кеш — чтение сразу видит документ.
        self.assertEqual(counters.project_counts(pid).get("documents", 0), 1)


if __name__ == "__main__":
    unittest.main()
