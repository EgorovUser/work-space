"""Реестр каналов уведомлений (патч AQ): единая точка расширения.

Что проверяем:

- каталог и дефолты матрицы приходят из реестра: browser, os, telegram,
  email в известном порядке, дефолт — только browser включён;
- register_channel добавляет канал в каталог, дефолты и матрицу (meta)
  даже после импорта настроек, а send диспетчеризует в его sender;
- клиентские каналы (browser, os) не считаются серверными — строк
  доставок не создают;
- send на неизвестный канал тихо помечается skipped;
- встроенные серверные каналы подписаны под контракт реестра: sender
  принимает ровно (user_id, subject, text) — регрессия AQ/AV, когда
  send_telegram с двумя параметрами ронял каждую telegram-доставку
  TypeError'ом (без токена — честный «failed», без сети);
- сквозной путь: fake-канал в матрице пользователя → handle() создаёт
  строку доставки → send_delivery зовёт sender реестра → статус sent.

Инициализация идемпотентна: при `unittest discover` первым импортируется
test_app (готовит env и конфиг); при одиночном запуске конфиг поднимаем сами.
"""

from __future__ import annotations

import inspect
import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-channels-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "channels-test-secret")
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

from sqlalchemy import select  # noqa: E402

from app.core import events_bus  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.core.events_catalog import PROJECT_CREATED  # noqa: E402
from app.core.outbox import dispatch_once, enqueue  # noqa: E402
from app.core.settings_store import reset_value, set_value  # noqa: E402
from app.modules.notifications import channels  # noqa: E402
from app.modules.notifications.channels import ChannelDef  # noqa: E402
from app.modules.notifications.models import NotificationDelivery  # noqa: E402

PASSWORD = "tester-pass"
MARK = "ch" + os.urandom(4).hex()


def _drain_all() -> None:
    for _ in range(60):
        if dispatch_once() == 0:
            break


class ChannelRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})

    @classmethod
    def tearDownClass(cls):
        client.post("/api/auth/logout")

    def test_catalog_from_registry(self):
        ids = [item["id"] for item in channels.catalog()]
        self.assertEqual(ids, ["browser", "os", "telegram", "email"])
        labels = {item["id"]: item["label"] for item in channels.catalog()}
        self.assertEqual(labels["browser"], "В приложении")
        self.assertEqual(labels["os"], "Системные уведомления")

    def test_default_flags(self):
        flags = channels.default_flags()
        self.assertTrue(flags["browser"])
        self.assertFalse(flags["os"])
        self.assertFalse(flags["telegram"])
        self.assertFalse(flags["email"])

    def test_client_channels_are_not_server(self):
        self.assertFalse(channels.is_server_channel("browser"))
        self.assertFalse(channels.is_server_channel("os"))
        self.assertTrue(channels.is_server_channel("telegram"))
        self.assertTrue(channels.is_server_channel("email"))

    def test_unknown_channel_send_is_skipped(self):
        status, error = channels.send("nosuch", 1, "тема", "текст")
        self.assertEqual(status, "skipped")
        self.assertEqual(error, "Неизвестный канал")
        status, error = channels.test_channel("browser", 1)
        self.assertEqual(status, "skipped")

    def test_server_senders_match_registry_contract(self):
        # Реестр диспетчеризует sender(user_id, subject, text) — сигнатура
        # каждого серверного отправителя обязана принимать ровно три
        # позиционных аргумента. Регрессия AV: send_telegram(user_id, text)
        # падал TypeError на первой же telegram-доставке в продакшене.
        for item in channels.all_channels():
            if not item.server_delivery or item.sender is None:
                continue
            with self.subTest(channel=item.id):
                params = list(inspect.signature(item.sender).parameters.values())
                self.assertTrue(
                    all(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) for p in params),
                    f"{item.id}: sender должен принимать позиционные аргументы",
                )
                self.assertEqual(len(params), 3, f"{item.id}: ожидается sender(user_id, subject, text)")

    def test_telegram_send_through_registry(self):
        # Без токена доставка честно отвечает «failed» с понятной причиной —
        # и больше не взрывается TypeError на входе (сеть не трогаем).
        status, error = channels.send("telegram", 1, "тема", "текст")
        self.assertEqual((status, error), ("failed", "Не задан токен бота"))
        # Кнопка «Проверить» идёт через ту же сигнатуру.
        status, error = channels.test_channel("telegram", 1)
        self.assertEqual((status, error), ("failed", "Не задан токен бота"))

    def test_email_send_through_registry(self):
        status, error = channels.send("email", 1, "тема", "текст")
        self.assertEqual((status, error), ("skipped", "Не задан сервер, отправитель или получатель"))

    def test_registered_channel_reaches_catalog_and_matrix(self):
        channels.register_channel(ChannelDef(id="fake" + MARK, label="Фейк"))
        try:
            self.assertIn("fake" + MARK, channels.default_flags())
            response = client.get("/api/notifications/meta")
            self.assertEqual(response.status_code, 200, response.text)
            meta = response.json()
            ids = [item["id"] for item in meta["channels"]]
            self.assertIn("fake" + MARK, ids)
            # у всех событий матрицы появился новый канал (выключенный)
            for flags in meta["matrix"].values():
                self.assertIn("fake" + MARK, flags)
                self.assertFalse(flags["fake" + MARK])
        finally:
            channels._registry.pop("fake" + MARK, None)

    def test_handle_delivers_through_registered_sender(self):
        code = "fake" + MARK
        calls: list[tuple[int, str]] = []
        channels.register_channel(
            ChannelDef(id=code, label="Фейк", sender=lambda uid, subject, text: (calls.append((uid, subject)), ("sent", ""))[1])
        )
        # Порядок важен: сначала разбираем хвост чужих событий (иначе каждое
        # оставшееся project.created тоже получит fake-доставку по нашей
        # матрице), и только потом включаем канал и кладём своё событие.
        _drain_all()
        set_value(
            "notifications",
            "matrix",
            "user",
            {"project.created": {"browser": False, code: True}},
            actor_id=1,
            user_id=1,
        )
        try:
            with session_scope() as session:
                enqueue(
                    session,
                    PROJECT_CREATED,
                    {"title": "реестр " + MARK, "subject": "реестр " + MARK},
                    user_id=1,
                )
            _drain_all()
            with session_scope() as session:
                rows = session.scalars(
                    select(NotificationDelivery).where(NotificationDelivery.channel == code)
                ).all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].status, "sent")
            self.assertEqual(calls, [(1, "реестр " + MARK)])
        finally:
            channels._registry.pop(code, None)
            reset_value("notifications", "matrix", "user", actor_id=1, user_id=1)


if __name__ == "__main__":
    unittest.main()
