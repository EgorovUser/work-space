from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, TypeDecorator, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import ROOT, get as get_config

_engine = None
SessionLocal: sessionmaker[Session] | None = None
_BUSY_DEFAULT = 25000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TZDateTime(TypeDecorator):
    """UTC в SQLite: в файле наивные метки, в Python — с таймзоной."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    global _engine, SessionLocal
    cfg = get_config()
    _engine = create_engine(
        cfg.sqlite_url(),
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=" + str(_busy_ms(cursor)))
        cursor.close()

    SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    from app.core import models  # noqa: F401
    from app.modules import import_models

    import_models()

    inspector = inspect(_engine)
    tables = set(inspector.get_table_names())
    alembic_cfg = Config(str(ROOT / "alembic.ini"))

    if not tables:
        # Свежая база: схема целиком через create_all (модели уже включают индексы)
        Base.metadata.create_all(_engine)
        command.stamp(alembic_cfg, "head")
    elif "alembic_version" not in tables:
        # Старая база до alembic: досоздаём недостающие таблицы и
        # проигрываем реальные миграции (0002+), а не перепрыгиваем их.
        # 0001 — baseline-заглушка («схема из create_all»), поэтому stamp на неё.
        Base.metadata.create_all(_engine)
        command.stamp(alembic_cfg, "0001")
        command.upgrade(alembic_cfg, "head")
    else:
        # База уже под управлением Alembic
        command.upgrade(alembic_cfg, "head")

    _warn_schema_drift()


def _warn_schema_drift() -> None:
    """Явно ругаемся в лог, если БД отстала от моделей.

    Иначе первый симптом дрейфа — криптичное "no such column" из глубины
    seed()/роутеров. Предупреждение называет таблицу и колонки.
    """
    from app.core.logging import logger

    inspector = inspect(_engine)
    existing_tables = set(inspector.get_table_names())
    problems: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            problems.append(f"нет таблицы {table.name}")
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        missing = [c.name for c in table.columns if c.name not in existing_cols]
        if missing:
            problems.append(f"{table.name}: нет колонок {', '.join(missing)}")
    if problems:
        logger.warning(
            "Схема БД отстала от моделей ({}): {} — добавьте миграцию",
            len(problems),
            "; ".join(problems),
        )


def session_factory() -> Session:
    if SessionLocal is None:
        raise RuntimeError("База ещё не открыта")
    return SessionLocal()


@contextmanager
def session_scope():
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def healthcheck() -> None:
    with session_scope() as session:
        session.execute(text("SELECT 1"))
        from app.core.settings_store import get_bool

        if get_bool("core", "db.quick_check"):
            rows = session.execute(text("PRAGMA quick_check")).all()
            verdict = [str(row[0]) for row in rows]
            if verdict != ["ok"]:
                raise RuntimeError("База повреждена: " + "; ".join(verdict)[:240])


def db_file() -> Path:
    url = get_config().sqlite_url()
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise RuntimeError("Это не файл SQLite")
    return Path(url[len(prefix):])


def db_info() -> dict:
    path = db_file()
    wal = Path(str(path) + "-wal")
    shm = Path(str(path) + "-shm")
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "wal_bytes": wal.stat().st_size if wal.is_file() else 0,
        "shm_bytes": shm.stat().st_size if shm.is_file() else 0,
    }


def integrity_check() -> str:
    with session_scope() as session:
        rows = session.execute(text("PRAGMA integrity_check")).all()
    verdict = [str(row[0]) for row in rows]
    if verdict != ["ok"]:
        raise RuntimeError("; ".join(verdict)[:500])
    return "Целостность в порядке"


def checkpoint() -> dict:
    _exec("PRAGMA wal_checkpoint(PASSIVE)")
    return db_info()


def vacuum() -> dict:
    _exec("VACUUM")
    return db_info()


def _exec(sql: str) -> None:
    if _engine is None:
        raise RuntimeError("База ещё не открыта")
    with _engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(sql)


def _busy_ms(cursor) -> int:
    try:
        cursor.execute(
            "SELECT value_json FROM setting_values WHERE module = ? AND key = ? AND scope_key = ?",
            ("core", "db.busy_timeout_ms", "global"),
        )
        row = cursor.fetchone()
        if row and row[0]:
            value = int(json.loads(row[0]))
            if 1000 <= value <= 120000:
                return value
    except Exception:
        pass
    return _BUSY_DEFAULT
