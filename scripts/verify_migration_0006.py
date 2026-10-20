"""Проверка миграционного пути 0005 -> 0006 на «старой» базе.

Симулируем управляемую базу на ревизии 0005 (без колонок повтора),
запускаем init_db() и убеждаемся, что колонки появились, а записи
задач сохранились. Запуск: PYTHONPATH=. python scripts/verify_migration_0006.py
"""

import os
import tempfile

_root = tempfile.mkdtemp(prefix="ws-mig-")
os.environ["DATA_DIR"] = _root
os.environ["APP_ENV"] = "dev"
os.environ["SECRET_KEY"] = "migration-check"
os.environ["SEED_USERNAME"] = "mig"
os.environ["SEED_PASSWORD"] = "mig-pass"
os.environ["LOG_LEVEL"] = "ERROR"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.core.config import prepare  # noqa: E402

prepare()

from app.core.bridge import on_project_created  # noqa: E402
from app.core.db import ROOT, init_db, session_scope  # noqa: E402
from app.core.settings_store import register_defs, sync_definitions  # noqa: E402
from app.modules.projects import service as projects  # noqa: E402
from app.modules.projects.settings import DEFS as PROJECT_DEFS  # noqa: E402
from app.modules.tasks import service as tasks  # noqa: E402
from app.modules.tasks.settings import DEFS as TASK_DEFS  # noqa: E402
from app.seed import seed  # noqa: E402

init_db()
for group in (PROJECT_DEFS, TASK_DEFS):
    register_defs(group)
sync_definitions()
seed()
on_project_created(tasks.seed_project)

cfg = Config(str(ROOT / "alembic.ini"))


def task_columns() -> set:
    with session_scope() as session:
        return {c["name"] for c in inspect(session.get_bind()).get_columns("tasks")}


with session_scope() as session:
    from sqlalchemy import select  # noqa: E402

    from app.core.models import User  # noqa: E402

    user_id = session.scalars(select(User.id)).first()
    card = projects.create_project(session, user_id, "Проверка миграции", "")
    project_id = card["id"]
    status_id = tasks.list_statuses(session, project_id)[0]["id"]

# Откатываемся к 0005 и имитируем старую базу: колонок повтора нет.
command.downgrade(cfg, "0005")
columns = task_columns()
assert "repeat_kind" not in columns, "колонки не должны существовать до миграции"

with session_scope() as session:
    session.execute(
        text(
            "INSERT INTO tasks (project_id, status_id, title, description, priority, progress_mode, progress_manual, position, created_at, updated_at) "
            "VALUES (:p, :s, 'старая', '', '', 'auto', 0, 0, '2026-10-20 00:00:00+00:00', '2026-10-20 00:00:00+00:00')"
        ),
        {"p": project_id, "s": status_id},
    )

# init_db на управляемой базе проигрывает upgrade('head') — путь ветки 3.
init_db()

columns = task_columns()
for name in ("repeat_kind", "repeat_interval", "repeat_until"):
    assert name in columns, "миграция не добавила колонку " + name

with session_scope() as session:
    row = session.execute(text("SELECT title, repeat_kind, repeat_interval, repeat_until FROM tasks")).first()
    assert row.title == "старая", "запись потерялась при миграции"
    assert row.repeat_kind == "" and row.repeat_interval == 1 and row.repeat_until is None

print("миграция 0005 -> 0006: OK, данные сохранены")
