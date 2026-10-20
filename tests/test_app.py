import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from cryptography.fernet import Fernet

_root = tempfile.mkdtemp(prefix="ws-test-")
os.environ["DATA_DIR"] = _root
os.environ["APP_ENV"] = "dev"
os.environ["SECRET_KEY"] = "unit-test-secret"
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["SEED_USERNAME"] = "tester"
os.environ["SEED_PASSWORD"] = "tester-pass"
os.environ["LOG_LEVEL"] = "ERROR"

from app.core.config import prepare  # noqa: E402

prepare()

from app.core.logging import bootstrap  # noqa: E402

bootstrap()

from sqlalchemy import select  # noqa: E402

from app.core.auth import hash_password, verify_password  # noqa: E402
from app.core.bridge import on_project_created  # noqa: E402
from app.core.db import init_db, session_scope  # noqa: E402
from app.core.files import save_bytes  # noqa: E402
from app.core.logging import mask  # noqa: E402
from app.core.models import StoredFile, User  # noqa: E402
from app.core.setting_defs import CORE_DEFS  # noqa: E402
from app.core.settings_store import SettingsError, get_bool, get_int, register_defs, set_value, sync_definitions  # noqa: E402
from app.core.status_check import status_lines  # noqa: E402
from app.modules.documents.settings import DEFS as DOC_DEFS  # noqa: E402
from app.modules.examples.settings import DEFS as EXAMPLE_DEFS  # noqa: E402
from app.modules.mail.ics import parse_ics  # noqa: E402
from app.modules.mail.parse import parse_message  # noqa: E402
from app.modules.mail.service import _fold_subject, _letter_matches_notify, _lookback_token  # noqa: E402
from app.modules.mail.settings import DEFS as MAIL_DEFS  # noqa: E402
from app.modules.notifications.settings import DEFS as NOTE_DEFS  # noqa: E402
from app.modules.projects import service as projects  # noqa: E402
from app.modules.projects.settings import DEFS as PROJECT_DEFS  # noqa: E402
from app.modules.secrets import service as secrets  # noqa: E402
from app.modules.secrets.settings import DEFS as SECRET_DEFS  # noqa: E402
from app.modules.tasks import service as tasks  # noqa: E402
from app.modules.tasks.service import recurrence  # noqa: E402
from app.modules.tasks.settings import DEFS as TASK_DEFS  # noqa: E402
from app.modules.timetracking.settings import DEFS as TIME_DEFS  # noqa: E402
from app.seed import seed  # noqa: E402


def setUpModule():
    init_db()
    for group in (
        CORE_DEFS,
        PROJECT_DEFS,
        TASK_DEFS,
        DOC_DEFS,
        EXAMPLE_DEFS,
        SECRET_DEFS,
        TIME_DEFS,
        MAIL_DEFS,
        NOTE_DEFS,
    ):
        register_defs(group)
    sync_definitions()
    seed()
    on_project_created(tasks.seed_project)


def _user_id() -> int:
    with session_scope() as session:
        return session.scalars(select(User.id)).one()


class LogicTests(unittest.TestCase):
    def test_mask_hides_secrets(self):
        text = mask("password=secret token: abc Bearer qqq gAAAAAabcdef==")
        self.assertNotIn("secret", text.split("password=", 1)[-1][:6])
        self.assertIn("***", text)
        self.assertNotIn("gAAAAA", text)

    def test_password_roundtrip(self):
        hashed = hash_password("correct horse")
        self.assertTrue(verify_password("correct horse", hashed))
        self.assertFalse(verify_password("wrong", hashed))

    def test_status_lines_skip_notifications(self):
        lines = status_lines(
            {
                "checks": [
                    {"id": "db", "label": "База", "status": "bad", "detail": "нет файла"},
                    {"id": "telegram", "label": "Telegram", "status": "bad", "detail": "токен"},
                    {"id": "mail", "label": "Почта", "status": "warn", "items": [
                        {"label": "Ящик", "status": "warn", "detail": "Ящиков нет"},
                        {"label": "Рабочий", "status": "bad", "detail": "таймаут"},
                    ]},
                ],
                "schedule": [
                    {"id": "notifications.deliver", "title": "Доставка", "status": "bad", "error": "упало"},
                    {"id": "mail.poll", "title": "Почта", "status": "bad", "error": "обрыв"},
                ],
            }
        )
        blob = " ".join(lines)
        self.assertIn("нет файла", blob)
        self.assertIn("таймаут", blob)
        self.assertIn("обрыв", blob)
        self.assertNotIn("токен", blob)
        self.assertNotIn("Доставка", blob)
        self.assertNotIn("Ящиков нет", blob)

    def test_fold_subject(self):
        folded = _fold_subject("Re: Автоматический ответ: Отчёт", ["автоматический ответ", "re", "fw"], 6)
        self.assertEqual(folded, "отчёт")

    def test_lookback_token(self):
        token = _lookback_token(0)
        self.assertRegex(token, r"^\d{2}-[A-Z][a-z]{2}-\d{4}$")

    def test_parse_mail_and_ics(self):
        msg = EmailMessage()
        msg["From"] = "Ivan <ivan@example.com>"
        msg["To"] = "me@example.com"
        msg["Subject"] = "Отчёт"
        msg["Message-ID"] = "<abc@example.com>"
        msg.set_content("Привет")
        parsed = parse_message(
            msg.as_bytes(),
            {"max_bytes": 100000, "subject": 200, "address": 200, "body": 1000, "html": 1000, "encodings": ["utf-8"], "events": 5, "zone": "UTC"},
        )
        self.assertEqual(parsed["from_addr"], "ivan@example.com")
        self.assertEqual(parsed["subject"], "Отчёт")
        self.assertIn("Привет", parsed["body"])
        events = parse_ics(
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20261016T090000Z\nSUMMARY:Созвон\nEND:VEVENT\nEND:VCALENDAR\n",
            "UTC",
            5,
        )
        self.assertEqual(events[0]["summary"], "Созвон")
        self.assertIsNotNone(events[0]["starts_at"])

    def test_recurrence_advance(self):
        user_id = _user_id()
        set_value("core", "ui.timezone", "global", "UTC", actor_id=user_id)
        daily = recurrence.advance(datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc), "daily", 3)
        self.assertEqual(daily, datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc))
        # Месяцы идут по календарю: 31 января + 1 = 28 февраля.
        monthly = recurrence.advance(datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc), "monthly", 1)
        self.assertEqual(monthly, datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc))
        # 29 февраля + 1 год = 28 февраля.
        yearly = recurrence.advance(datetime(2024, 2, 29, 10, 0, tzinfo=timezone.utc), "yearly", 1)
        self.assertEqual(yearly, datetime(2025, 2, 28, 10, 0, tzinfo=timezone.utc))

    def test_recurrence_next_deadline_catches_up(self):
        from app.modules.tasks.models import Task as TaskRow

        user_id = _user_id()
        set_value("core", "ui.timezone", "global", "UTC", actor_id=user_id)
        now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        # Дедлайн 1 октября, закрыли 20-го: вхождение не в прошлое, а 22-го.
        task = TaskRow(deadline=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc), repeat_kind="weekly", repeat_interval=1)
        self.assertEqual(recurrence.next_deadline(task, now), datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc))
        # Дедлайн ещё впереди: следующий — ровно на шаг позже, не тот же день.
        early = TaskRow(deadline=datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc), repeat_kind="weekly", repeat_interval=1)
        self.assertEqual(recurrence.next_deadline(early, now), datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc))
        # Серия закончилась: граница прошла, повтора нет.
        ended = TaskRow(
            deadline=datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc),
            repeat_kind="weekly",
            repeat_interval=1,
            repeat_until=datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc),
        )
        self.assertIsNone(recurrence.next_deadline(ended, now))
        # Граница включается календарным днём.
        last = TaskRow(
            deadline=datetime(2026, 10, 22, 18, 0, tzinfo=timezone.utc),
            repeat_kind="weekly",
            repeat_interval=1,
            repeat_until=datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(recurrence.next_deadline(last, now), datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc))


class StoreTests(unittest.TestCase):
    def test_project_task_and_column_order(self):
        user_id = _user_id()
        with session_scope() as session:
            card = projects.create_project(session, user_id, "Тест", "")
            project_id = card["id"]
            statuses = tasks.list_statuses(session, project_id)
            self.assertGreaterEqual(len(statuses), 2)
            task = tasks.create_task(session, project_id, user_id, {"title": "Сделать"})
            self.assertEqual(task["title"], "Сделать")
            ids = [item["id"] for item in statuses]
            reversed_ids = list(reversed(ids))
            ordered = tasks.order_statuses(session, project_id, user_id, reversed_ids)
            self.assertEqual([item["id"] for item in ordered], reversed_ids)
            with self.assertRaises(Exception):
                tasks.order_statuses(session, project_id, user_id, reversed_ids[:-1])

    def test_task_recurrence_spawns_next(self):
        user_id = _user_id()
        set_value("core", "ui.timezone", "global", "UTC", actor_id=user_id)
        with session_scope() as session:
            card = projects.create_project(session, user_id, "Повторы", "")
            project_id = card["id"]
            closed_id = next(item["id"] for item in tasks.list_statuses(session, project_id) if item["is_closed"])
            tag = tasks.create_tag(session, project_id, user_id, "ритм")
            due = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            task = tasks.create_task(
                session,
                project_id,
                user_id,
                {"title": "Полив", "deadline": due.isoformat(), "repeat_kind": "weekly", "tag_ids": [tag["id"]]},
            )
            self.assertEqual(task["repeat_kind"], "weekly")
            check = tasks.add_check(session, project_id, user_id, task["id"], "Налить воду")
            tasks.update_check(session, project_id, user_id, task["id"], check["id"], {"done": True})

            closed = tasks.update_task(session, project_id, user_id, task["id"], {"status_id": closed_id})
            self.assertIsNotNone(closed["closed_at"])

            items = tasks.list_tasks(session, project_id)["items"]
            spawned = [item for item in items if item["title"] == "Полив" and item["id"] != task["id"]]
            self.assertEqual(len(spawned), 1)
            self.assertEqual(spawned[0]["deadline"], (due + timedelta(days=7)).isoformat())
            self.assertEqual(spawned[0]["repeat_kind"], "weekly")

            fresh = tasks.get_task(session, project_id, spawned[0]["id"])
            self.assertEqual([item["title"] for item in fresh["checklist"]], ["Налить воду"])
            self.assertFalse(fresh["checklist"][0]["done"])
            self.assertEqual([item["name"] for item in fresh["tags"]], ["ритм"])
            # Лента: у вхождения — «создана» с пометкой, у исходной — «повтор».
            self.assertEqual([item["kind"] for item in fresh["events"]], ["created"])
            source = tasks.get_task(session, project_id, task["id"])
            self.assertIn("recur", [item["kind"] for item in source["events"]])

            # Обычная задача при закрытии ничего не плодит.
            plain = tasks.create_task(session, project_id, user_id, {"title": "Разовая"})
            tasks.update_task(session, project_id, user_id, plain["id"], {"status_id": closed_id})
            items = tasks.list_tasks(session, project_id)["items"]
            self.assertEqual(len([item for item in items if item["title"] == "Разовая"]), 1)

            # Серия с прошедшей границей не продолжается.
            finished = tasks.create_task(
                session,
                project_id,
                user_id,
                {
                    "title": "Завершённая серия",
                    "deadline": due.isoformat(),
                    "repeat_kind": "daily",
                    "repeat_until": (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat(),
                },
            )
            tasks.update_task(session, project_id, user_id, finished["id"], {"status_id": closed_id})
            items = tasks.list_tasks(session, project_id)["items"]
            self.assertEqual(len([item for item in items if item["title"] == "Завершённая серия"]), 1)

    def test_secret_roundtrip_and_file_dedup(self):
        user_id = _user_id()
        with session_scope() as session:
            card = projects.create_project(session, user_id, "Секреты", "")
            project_id = card["id"]
            created = secrets.create_secret(
                session,
                project_id,
                user_id,
                {"title": "Ключ", "kind": "password", "username": "ivan", "secret": "p@ss"},
            )
            opened = secrets.reveal_secret(session, project_id, user_id, created["id"])
            self.assertEqual(opened["secret"], "p@ss")
            first = save_bytes(session, b"same-bytes", "a.txt", "text/plain", user_id)
            second = save_bytes(session, b"same-bytes", "b.txt", "text/plain", user_id)
            self.assertEqual(first.id, second.id)
            count = session.scalar(select(StoredFile).where(StoredFile.sha256 == first.sha256))
            self.assertIsNotNone(count)

    def test_settings_bounds_and_mail_filter(self):
        user_id = _user_id()
        set_value("core", "db.busy_timeout_ms", "global", 5000, actor_id=user_id)
        self.assertEqual(get_int("core", "db.busy_timeout_ms"), 5000)
        with self.assertRaises(SettingsError):
            set_value("core", "db.busy_timeout_ms", "global", 10, actor_id=user_id)
        self.assertTrue(get_bool("mail", "fetch.notify_new"))
        self.assertEqual(get_int("mail", "fetch.lookback_days"), 7)
        with session_scope() as session:
            self.assertTrue(_letter_matches_notify(session, None))
        set_value("mail", "notify.mode", "global", "filter", actor_id=user_id)
        with session_scope() as session:
            self.assertFalse(_letter_matches_notify(session, None))
        set_value("mail", "notify.mode", "global", "all", actor_id=user_id)

    def test_data_dir_is_temporary(self):
        self.assertTrue(str(Path(os.environ["DATA_DIR"])).startswith(tempfile.gettempdir()))
        self.assertTrue((Path(_root) / "app.db").is_file())


if __name__ == "__main__":
    unittest.main()
