"""Вложение письма → документ (патч N) и жадное сохранение при импорте.

Инварианты:
- ручной импорт .eml сразу сохраняет байты вложений (сервера-источника
  нет, позже взять неоткуда);
- POST .../attachments/{section}/document создаёт документ с версией
  и извлечённым текстом, не перезаливая файл;
- из общего ящика проект указывается в теле запроса;
- несуществующая секция — 404; аноним — 401.
"""

from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-maildoc-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "maildoc-test-secret")
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

MARK = "maildoc" + os.urandom(4).hex()


def _login() -> None:
    client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})


def _project(name: str) -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _eml_with_attachment(subject: str, filename: str, payload: bytes) -> bytes:
    import base64

    boundary = "mixed-" + MARK
    encoded_subject = base64.b64encode(subject.encode()).decode()
    headers = [
        "From: Отправитель <sender@corp.example>",
        "To: tester <tester@corp.example>",
        f"Subject: =?utf-8?B?{encoded_subject}?=",
        "Date: Mon, 19 Oct 2026 10:00:00 +0000",
        f"Message-ID: <{MARK}-{abs(hash(subject))}@corp.example>",
        "MIME-Version: 1.0",
        f'Content-Type: multipart/mixed; boundary="{boundary}"',
        "",
        f"--{boundary}",
        'Content-Type: text/plain; charset=utf-8',
        "",
        "Тело письма с вложением.",
        "",
        f"--{boundary}",
        f'Content-Type: text/plain; name="{filename}"',
        f'Content-Disposition: attachment; filename="{filename}"',
        "Content-Transfer-Encoding: base64",
        "",
        base64.b64encode(payload).decode(),
        "",
        f"--{boundary}--",
        "",
    ]
    return ("\r\n".join(headers)).encode("utf-8")


def _import(project_id: int, raw: bytes) -> int:
    response = client.post(
        f"/api/projects/{project_id}/mail/import",
        files={"file": ("letter.eml", raw, "message/rfc822")},
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()
    assert payload["status"] == "stored", payload
    return payload["id"]


class AttachmentToDocumentTest(unittest.TestCase):
    def setUp(self):
        client.post("/api/auth/logout")
        _login()
        self.project = _project("Почта→документы " + MARK)
        self.other = _project("Другой проект " + MARK)
        # Письмо видно в ящике проекта, если совпадает правило раскладки.
        rule = client.post(
            f"/api/projects/{self.project['id']}/mail/rules",
            json={"name": "Отправитель", "field": "from", "op": "contains", "value": "corp.example", "action": "keep"},
        )
        assert rule.status_code == 201, rule.text
        self.payload = ("Отчёт: строка один\nстрока два\n" + MARK).encode("utf-8")
        raw = _eml_with_attachment("Счёт за октябрь " + MARK, "report-" + MARK + ".txt", self.payload)
        self.message_id = _import(self.project["id"], raw)

    def _message(self) -> dict:
        return client.get(f"/api/projects/{self.project['id']}/mail/messages/{self.message_id}").json()

    def test_import_stores_attachment_bytes(self):
        message = self._message()
        self.assertTrue(message["attachments"])
        item = message["attachments"][0]
        self.assertEqual(item["filename"], "report-" + MARK + ".txt")
        # Файл уже сохранён: есть file_id, скачивание идёт напрямую.
        self.assertTrue(item["file_id"])

    def test_project_endpoint_creates_document(self):
        message = self._message()
        section = message["attachments"][0]["section"]
        response = client.post(
            f"/api/projects/{self.project['id']}/mail/messages/{self.message_id}/attachments/{section}/document"
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertEqual(payload["project_id"], self.project["id"])
        self.assertIn("report-" + MARK, payload["title"])

        document = client.get(
            f"/api/projects/{self.project['id']}/documents/{payload['document_id']}"
        ).json()
        self.assertIn("report-" + MARK, document["title"])
        # Извлечённый текст на месте: файл был text/plain.
        text = client.get(
            f"/api/projects/{self.project['id']}/documents/{payload['document_id']}/text"
        ).json()
        self.assertIn(MARK, text["text"])
        # Записи о письме не тронуты, вложение остаётся при письме.
        message_again = self._message()
        self.assertTrue(message_again["attachments"][0]["file_id"])

    def test_global_endpoint_uses_body_project(self):
        message = self._message()
        section = message["attachments"][0]["section"]
        response = client.post(
            f"/api/mail/messages/{self.message_id}/attachments/{section}/document",
            json={"project_id": self.other["id"]},
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertEqual(payload["project_id"], self.other["id"])
        listed = client.get(f"/api/projects/{self.other['id']}/documents").json()
        self.assertIn(payload["title"], [item["title"] for item in listed["items"]])

    def test_unknown_section_404(self):
        response = client.post(
            f"/api/projects/{self.project['id']}/mail/messages/{self.message_id}/attachments/999/document"
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_401(self):
        client.post("/api/auth/logout")
        response = client.post(
            f"/api/projects/{self.project['id']}/mail/messages/{self.message_id}/attachments/1/document"
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
