from __future__ import annotations

from collections.abc import Callable

from app.core.logging import log_scope, logger

_records: dict[str, dict] = {}


class ModuleDisabled(Exception):
    def __init__(self, module: str):
        self.module = module
        super().__init__(module)


def try_register(name: str, setup: Callable[[], None]) -> None:
    try:
        with log_scope("registry", "module.init"):
            setup()
        _records[name] = {"status": "ok", "error": None}
        logger.info("module ready name={}", name)
    except Exception as exc:
        message = str(exc)[:500]
        _records[name] = {"status": "error", "error": message}
        with log_scope("registry", "module.init"):
            logger.exception("module failed name={}", name)
        _enqueue_module_error(name, message)


def mark(name: str, status: str, error: str | None = None) -> None:
    _records[name] = {"status": status, "error": error}


def snapshot() -> dict[str, dict]:
    return {name: dict(record) for name, record in _records.items()}


def is_enabled(name: str) -> bool:
    record = _records.get(name)
    return bool(record and record["status"] == "ok")


def _enqueue_module_error(name: str, message: str) -> None:
    try:
        from app.core.db import session_scope
        from app.core.events_catalog import SYSTEM_MODULE_ERROR
        from app.core.outbox import enqueue

        with session_scope() as session:
            enqueue(
                session,
                SYSTEM_MODULE_ERROR,
                {"module": name, "error": message},
            )
    except Exception:
        with log_scope("registry", "module.init"):
            logger.exception("could not enqueue module error name={}", name)
