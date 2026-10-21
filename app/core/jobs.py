from __future__ import annotations

import time
from pathlib import Path

from app.core.config import get as get_config
from app.core.logging import logger
from app.core.settings_store import get_int


def cleanup_logs() -> None:
    days = get_int("core", "logs.retention_days")
    cutoff = time.time() - days * 24 * 60 * 60
    log_dir = get_config().data_path() / "logs"
    if not log_dir.exists():
        return
    active = _active_logs(log_dir)
    for path in log_dir.iterdir():
        if not path.is_file():
            continue
        if path.name in active:
            continue
        if path.stat().st_mtime >= cutoff:
            continue
        path.unlink()
        logger.info("log removed file={}", path.name)


def _active_logs(log_dir: Path) -> set[str]:
    """Файлы, которые сейчас могут быть открыты процессом."""
    names = {"app.log", "errors.log", "uvicorn.log"}
    return names


def register_core_jobs() -> None:
    from app.core.scheduler import register_job
    from app.core.status_check import watch

    register_job(
        name="logs.cleanup",
        fn=cleanup_logs,
        module="core",
        action="job.logs.cleanup",
        interval_module="core",
        interval_key="logs.cleanup_interval_hours",
        interval_unit="hours",
        label="Журнал",
        detail="Удаляет старые файлы журнала",
    )
    register_job(
        name="outbox.cleanup",
        fn=cleanup_outbox,
        module="core",
        action="job.outbox.cleanup",
        interval_module="core",
        interval_key="outbox.cleanup_interval_hours",
        interval_unit="hours",
        label="Очередь событий",
        detail="Удаляет отработанные события старше retention (DONE — дни, FAILED — вчетверо дольше)",
    )
    register_job(
        name="system.watch",
        fn=watch,
        module="core",
        action="watch",
        interval_module="core",
        interval_key="watch.seconds",
        label="Состояние",
        detail="Пишет, если сломалось что-то кроме самих уведомлений",
        enabled_module="core",
        enabled_key="watch.notify",
    )
