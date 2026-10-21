"""Джобы ядра регистрируются целиком (регрессия патча AU).

register_core_jobs вызывается из lifespan планировщика, а юнит-тесты
сознательно не поднимают lifespan (TestClient без контекст-менеджера —
джобы не мешают). Поэтому NameError в fn= доживал до продакшена: модуль
scheduler падал в try_register, поток не стартовал, а фоновые джобы
(часы по таймеру, доставка уведомлений, сторож состояния) умирали молча.
Здесь регистрацию проверяем напрямую; живой старт дополнительно охраняет
e2e-тест healthz (требует status=ok и модули без ошибок).

Инициализация идемпотентна: при `unittest discover` первым импортируется
test_app (готовит env и конфиг); при одиночном запуске конфиг поднимаем сами.
"""

from __future__ import annotations

import os
import tempfile
import unittest

_root = tempfile.mkdtemp(prefix="ws-core-jobs-")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("SECRET_KEY", "core-jobs-test-secret")
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

from app.main import app  # noqa: E402,F401  (импорт поднимает init_db + seed)

from app.core import scheduler  # noqa: E402
from app.core.jobs import register_core_jobs  # noqa: E402
from app.core.outbox import cleanup_outbox  # noqa: E402
from app.core.scheduler import job_names  # noqa: E402


class CoreJobsTest(unittest.TestCase):
    def test_core_jobs_register_without_name_errors(self):
        # До AU: fn=cleanup_outbox без импорта -> NameError, весь
        # планировщик не поднимался («Поток не запущен» на «Состоянии»).
        register_core_jobs()
        names = job_names()
        for expected in ("logs.cleanup", "outbox.cleanup", "system.watch"):
            self.assertIn(expected, names)

    def test_outbox_cleanup_job_points_at_outbox_function(self):
        # Регистрируется именно чистильщик очереди из app.core.outbox,
        # а не случайно завязанное имя.
        register_core_jobs()
        job = scheduler._jobs["outbox.cleanup"]
        self.assertIs(job.fn, cleanup_outbox)


if __name__ == "__main__":
    unittest.main()
