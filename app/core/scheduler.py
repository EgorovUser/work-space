from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.context import request_id_var
from app.core.logging import log_scope, logger

_jobs: dict[str, Job] = {}
_next: dict[str, float] = {}
_last: dict[str, dict] = {}
_running_long: set[str] = set()
_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None

# Долгие джобы, которые не должны блокировать быстрые
_LONG_JOBS = {"mail.poll", "documents.extract"}


@dataclass
class Job:
    name: str
    fn: Callable[[], None]
    module: str
    action: str
    interval_module: str
    interval_key: str
    interval_unit: str
    label: str = ""
    detail: str = ""
    enabled_module: str = ""
    enabled_key: str = ""


def register_job(
    name: str,
    fn: Callable[[], None],
    *,
    module: str,
    action: str,
    interval_module: str,
    interval_key: str,
    interval_unit: str = "seconds",
    label: str = "",
    detail: str = "",
    enabled_module: str = "",
    enabled_key: str = "",
) -> None:
    with _lock:
        _jobs[name] = Job(
            name=name,
            fn=fn,
            module=module,
            action=action,
            interval_module=interval_module,
            interval_key=interval_key,
            interval_unit=interval_unit,
            label=label,
            detail=detail,
            enabled_module=enabled_module,
            enabled_key=enabled_key,
        )
        _next[name] = 0


def job_names() -> list[str]:
    with _lock:
        return sorted(_jobs)


def running() -> bool:
    return _thread is not None and _thread.is_alive()


def report() -> list[dict]:
    with _lock:
        jobs = list(_jobs.values())
        last = {name: dict(item) for name, item in _last.items()}
        nxt = dict(_next)
    now = time.monotonic()
    items = []
    for job in sorted(jobs, key=lambda item: item.name):
        info = last.get(job.name) or {}
        every = _interval_seconds(job)
        due = nxt.get(job.name, 0)
        next_in = 0 if due <= now else int(due - now)
        items.append(
            {
                "name": job.name,
                "label": job.label or job.name,
                "detail": job.detail or job.label or job.name,
                "ok": info.get("ok"),
                "error": info.get("error") or "",
                "finished_at": info.get("finished_at") or "",
                "every_seconds": every,
                "next_in_seconds": next_in,
                "enabled": _enabled(job),
            }
        )
    return items


def setup() -> None:
    from app.core.jobs import register_core_jobs

    register_core_jobs()
    start()
    if "logs.cleanup" not in job_names():
        raise RuntimeError("джоба logs.cleanup не зарегистрирована")
    if _thread is None or not _thread.is_alive():
        raise RuntimeError("планировщик не запущен")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=30)


def should_stop() -> bool:
    """Джобы могут проверять это между шагами и завершаться раньше."""
    return _stop.is_set()


def _loop() -> None:
    while not _stop.is_set():
        with _lock:
            jobs = list(_jobs.values())
        for job in jobs:
            if _stop.is_set():
                break
            interval = _interval_seconds(job)
            now = time.monotonic()
            due = _next.get(job.name, 0)
            if now < due:
                continue
            if job.name in _LONG_JOBS:
                _start_long(job)
            else:
                _run(job)
            _next[job.name] = time.monotonic() + interval
        _stop.wait(_tick_seconds())


def _start_long(job: Job) -> None:
    with _lock:
        if job.name in _running_long:
            logger.info("job skip already running name={}", job.name)
            return
        _running_long.add(job.name)
    thread = threading.Thread(target=_run_long, args=(job,), name="job-" + job.name, daemon=True)
    thread.start()


def _run_long(job: Job) -> None:
    try:
        _run(job)
    finally:
        with _lock:
            _running_long.discard(job.name)


def _run(job: Job) -> None:
    token = request_id_var.set("job:" + job.name + ":" + str(int(time.time())))
    try:
        with log_scope(job.module, job.action):
            logger.info("job start name={}", job.name)
            try:
                job.fn()
                logger.info("job done name={}", job.name)
                _remember(job.name, True, "")
            except Exception as exc:
                logger.opt(exception=True).warning("job failed name={}", job.name)
                _remember(job.name, False, str(exc) or "ошибка")
    finally:
        request_id_var.reset(token)


def _remember(name: str, ok: bool, error: str) -> None:
    with _lock:
        _last[name] = {
            "ok": ok,
            "error": (error or "")[:300],
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }


def _enabled(job: Job) -> bool:
    if not job.enabled_key:
        return True
    try:
        from app.core.settings_store import get_bool

        return get_bool(job.enabled_module or job.interval_module, job.enabled_key)
    except Exception:
        with log_scope("scheduler", "interval"):
            logger.opt(exception=True).warning("job enabled failed name={}", job.name)
        return True


def _interval_seconds(job: Job) -> int:
    try:
        from app.core.settings_store import get_int

        raw = get_int(job.interval_module, job.interval_key)
        seconds = raw * 3600 if job.interval_unit == "hours" else raw
        return max(1, int(seconds))
    except Exception:
        with log_scope("scheduler", "interval"):
            logger.opt(exception=True).warning("job interval failed name={}", job.name)
        return 60


def _tick_seconds() -> int:
    try:
        from app.core.settings_store import get_int

        return max(1, get_int("core", "scheduler.tick_seconds"))
    except Exception:
        return 1
