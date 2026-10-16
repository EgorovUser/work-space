"""Живая проверка. Не кэш со старта: каждый вызов заново трогает базу, файлы, почту и каналы."""

from __future__ import annotations

from app.core.db import session_scope, utcnow
from app.core.logging import log_scope, logger


def run_checks(user_id: int) -> dict:
    checks = [
        _call("db", "База", _database),
        _call("files", "Файлы", _files),
        _call("settings", "Настройки", _settings),
        _call("auth", "Пользователи", _users),
        _scheduler(),
        _outbox(),
        _modules(),
    ]
    try:
        from app.modules.mail import service as mail_service

        with session_scope() as session:
            mail_items = mail_service.probe_accounts(session, user_id)
            events = mail_service.probe_events(session)
        checks.append(_items("mail", "Почта", mail_items))
        checks.append(events)
    except Exception as exc:
        checks.append({"id": "mail", "label": "Почта", "status": "bad", "detail": _text(exc), "items": []})
    checks.append(_channel("telegram", "Telegram", user_id))
    checks.append(_channel("email", "Почта уведомлений", user_id))
    jobs = _jobs()
    schedule = _schedule(jobs)
    status = _worst([item["status"] for item in checks] + _job_statuses(jobs))
    with log_scope("core", "status", user_id=user_id):
        logger.info("status check result={}", status)
    return {
        "status": status,
        "checked_at": utcnow().isoformat(),
        "checks": checks,
        "jobs": jobs,
        "schedule": schedule,
    }


def _database() -> str:
    from app.core.db import healthcheck

    healthcheck()
    return "Запрос прошёл"


def _files() -> str:
    from app.core.files import healthcheck

    healthcheck()
    return "Каталог пишется"


def _settings() -> str:
    from app.core.settings_store import healthcheck

    healthcheck()
    return "Читаются"


def _users() -> str:
    from app.core.auth import healthcheck

    healthcheck()
    return "Список открывается"


def _scheduler() -> dict:
    from app.core.scheduler import job_names, running

    names = job_names()
    if not running():
        return {"id": "scheduler", "label": "Планировщик", "status": "bad", "detail": "Поток не запущен"}
    return {
        "id": "scheduler",
        "label": "Планировщик",
        "status": "ok",
        "detail": "Работает, джоб " + str(len(names)),
    }


def _outbox() -> dict:
    from app.core.outbox import running, stats

    if not running():
        return {"id": "outbox", "label": "Очередь", "status": "bad", "detail": "Поток не запущен"}
    try:
        data = stats()
    except Exception as exc:
        return {"id": "outbox", "label": "Очередь", "status": "bad", "detail": _text(exc)}
    failed = int(data.get("failed") or 0)
    pending = int(data.get("pending") or 0)
    detail = "Ждут " + str(pending) + ", с ошибкой " + str(failed)
    return {"id": "outbox", "label": "Очередь", "status": "warn" if failed else "ok", "detail": detail}


def _modules() -> dict:
    from app.core.registry import snapshot

    modules = snapshot()
    broken = [name + ": " + str(item.get("error") or "ошибка") for name, item in modules.items() if item.get("status") != "ok"]
    if broken:
        return {"id": "modules", "label": "Модули", "status": "bad", "detail": "; ".join(broken)}
    names = ", ".join(sorted(modules)) or "нет"
    return {"id": "modules", "label": "Модули", "status": "ok", "detail": names}


def _channel(kind: str, label: str, user_id: int) -> dict:
    from app.modules.notifications import channels

    try:
        if kind == "telegram":
            status, detail = channels.check_telegram(user_id)
        else:
            status, detail = channels.check_email(user_id)
    except Exception as exc:
        status, detail = "bad", _text(exc)
    return {"id": kind, "label": label, "status": status, "detail": detail}


def _jobs() -> list[dict]:
    from app.core.scheduler import report

    try:
        return report()
    except Exception:
        logger.exception("job report failed")
        return []


def _schedule(jobs: list[dict]) -> list[dict]:
    rows = []
    try:
        for job in jobs:
            if job.get("name") == "mail.poll":
                rows.extend(_mail_rows(job))
            else:
                rows.append(_job_row(job))
        rows.extend(_loops())
        rows.sort(key=lambda item: item.get("every_seconds") or 0)
        for row in rows:
            row.pop("every_seconds", None)
    except Exception:
        logger.exception("schedule failed")
    return rows


def _job_row(job: dict) -> dict:
    enabled = bool(job.get("enabled"))
    return {
        "id": job.get("name") or "",
        "title": job.get("label") or job.get("name") or "",
        "every": _every(int(job.get("every_seconds") or 1)),
        "action": job.get("detail") or "",
        "next": _through(int(job.get("next_in_seconds") or 0)) if enabled else "Сейчас не выполняется",
        "finished_at": job.get("finished_at") or "",
        "error": job.get("error") or "",
        "status": _job_status(job, enabled),
        "every_seconds": int(job.get("every_seconds") or 1),
    }


def _mail_rows(job: dict) -> list[dict]:
    from app.modules.mail.service import schedule_accounts

    accounts = schedule_accounts()
    every = _every(int(job.get("every_seconds") or 1))
    if not accounts:
        return [
            {
                "id": "mail.poll",
                "title": "Почта",
                "every": every,
                "action": "Ящиков нет",
                "next": "",
                "finished_at": "",
                "error": "",
                "status": "warn",
                "every_seconds": int(job.get("every_seconds") or 1),
            }
        ]
    rows = []
    for account in accounts:
        enabled = bool(job.get("enabled")) and account["enabled"] and not account["blocked"]
        if not job.get("enabled"):
            action = "Забор выключен в настройках"
            status = "off"
        elif not account["enabled"]:
            action = "Ящик выключен"
            status = "off"
        elif account["blocked"]:
            action = "Пароль не подошёл, повторных попыток нет"
            status = "warn"
        else:
            action = "Сверяет письма за последние " + str(_lookback_days()) + " дн. и докачивает ещё не скачанные"
            status = _job_status(job, True)
        rows.append(
            {
                "id": "mail:" + str(account["id"]),
                "title": "Почта " + account["name"],
                "every": every,
                "action": action,
                "next": _through(int(job.get("next_in_seconds") or 0)) if enabled else "Сейчас не выполняется",
                "finished_at": job.get("finished_at") or "" if enabled else "",
                "error": job.get("error") or "" if enabled else "",
                "status": status,
                "every_seconds": int(job.get("every_seconds") or 1),
            }
        )
    return rows


def _loops() -> list[dict]:
    from app.core.outbox import poll_state
    from app.core.settings_store import get_int

    rows = []
    try:
        state = poll_state()
        running = bool(state.get("running"))
        rows.append(
            {
                "id": "outbox",
                "title": "Очередь событий",
                "every": _every(int(state.get("every_seconds") or 1)),
                "action": "Разбирает события и создаёт уведомления",
                "next": _through(int(state.get("next_in_seconds") or 0)) if running else "Поток не запущен",
                "finished_at": "",
                "error": "",
                "status": "ok" if running else "bad",
                "every_seconds": int(state.get("every_seconds") or 1),
            }
        )
    except Exception as exc:
        rows.append(
            {
                "id": "outbox",
                "title": "Очередь событий",
                "every": "",
                "action": _text(exc),
                "next": "",
                "finished_at": "",
                "error": "",
                "status": "bad",
                "every_seconds": 0,
            }
        )
    try:
        seconds = get_int("core", "ui.poll_notifications_seconds")
    except Exception:
        seconds = 30
    rows.append(
        {
            "id": "bell",
            "title": "Колокольчик",
            "every": _every(seconds),
            "action": "Открытая вкладка спрашивает непрочитанные",
            "next": "Пока страница открыта",
            "finished_at": "",
            "error": "",
            "status": "ok",
            "every_seconds": seconds,
        }
    )
    return rows


def _lookback_days() -> int:
    from app.core.settings_store import get_int

    try:
        return get_int("mail", "fetch.lookback_days")
    except Exception:
        return 7


def _job_status(job: dict, enabled: bool) -> str:
    if not enabled:
        return "off"
    if job.get("ok") is False:
        return "bad"
    if job.get("ok") is True:
        return "ok"
    return "warn"


def _every(seconds: int) -> str:
    seconds = max(1, int(seconds))
    if seconds % 3600 == 0:
        return _every_n(seconds // 3600, "час", "часа", "часов", "m")
    if seconds % 60 == 0:
        return _every_n(seconds // 60, "минуту", "минуты", "минут", "f")
    return _every_n(seconds, "секунду", "секунды", "секунд", "f")


def _through(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds <= 1:
        return "Следующий запуск сейчас"
    if seconds >= 3600 or (seconds >= 60 and round(seconds / 60) >= 60):
        hours = max(1, round(seconds / 3600))
        return "Следующий запуск через " + _span(hours, "час", "часа", "часов", "m")
    if seconds >= 60:
        minutes = max(1, round(seconds / 60))
        return "Следующий запуск через " + _span(minutes, "минуту", "минуты", "минут", "f")
    return "Следующий запуск через " + _span(seconds, "секунду", "секунды", "секунд", "f")


def _every_n(count: int, one: str, few: str, many: str, gender: str) -> str:
    if count == 1:
        return ("Каждую " if gender == "f" else "Каждый ") + one
    return "Каждые " + str(count) + " " + _ru(count, one, few, many)


def _span(count: int, one: str, few: str, many: str, gender: str) -> str:
    if count == 1:
        return ("одну " if gender == "f" else "один ") + one
    return str(count) + " " + _ru(count, one, few, many)


def _ru(count: int, one: str, few: str, many: str) -> str:
    number = abs(int(count)) % 100
    if 11 <= number <= 14:
        return many
    tail = number % 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def _items(check_id: str, label: str, items: list[dict]) -> dict:
    status = _worst([item.get("status") or "bad" for item in items] or ["warn"])
    details = [item.get("detail") or "" for item in items if item.get("detail")]
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": details[0] if len(details) == 1 else "",
        "items": items,
    }


def _call(check_id: str, label: str, fn) -> dict:
    try:
        return {"id": check_id, "label": label, "status": "ok", "detail": fn()}
    except Exception as exc:
        return {"id": check_id, "label": label, "status": "bad", "detail": _text(exc)}


def _job_statuses(jobs: list[dict]) -> list[str]:
    result = []
    for job in jobs:
        if job.get("ok") is False:
            result.append("warn")
    return result


def _worst(statuses: list[str]) -> str:
    if "bad" in statuses:
        return "bad"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _text(exc: Exception) -> str:
    return (str(exc) or "Ошибка")[:300]


_SKIP_CHECKS = {"telegram", "email", "outbox", "bell"}
_QUIET = {"Ящиков нет"}


def status_lines(report: dict) -> list[str]:
    lines = []
    for item in report.get("checks") or []:
        if item.get("id") in _SKIP_CHECKS:
            continue
        nested = item.get("items") or []
        if nested:
            for sub in nested:
                if sub.get("status") not in ("bad", "warn"):
                    continue
                detail = sub.get("detail") or ""
                if detail in _QUIET:
                    continue
                name = sub.get("label") or sub.get("name") or item.get("label") or ""
                lines.append(name + ": " + (detail or sub.get("status") or ""))
            continue
        if item.get("status") not in ("bad", "warn"):
            continue
        lines.append((item.get("label") or item.get("id") or "") + ": " + (item.get("detail") or item.get("status") or ""))
    for row in report.get("schedule") or []:
        name = str(row.get("id") or "")
        if name in _SKIP_CHECKS or name.startswith("notifications"):
            continue
        if row.get("status") != "bad":
            continue
        lines.append((row.get("title") or name) + ": " + (row.get("error") or row.get("action") or "ошибка"))
    return lines


def watch() -> None:
    from app.core.settings_store import get_bool

    if not get_bool("core", "watch.notify"):
        return
    from sqlalchemy import select

    from app.core.models import User

    with session_scope() as session:
        user_id = session.scalar(select(User.id).where(User.is_active.is_(True)).order_by(User.id)) or 0
    report = run_checks(int(user_id))
    with session_scope() as session:
        _note(session, status_lines(report))


def _note(session, lines: list[str]) -> None:
    from sqlalchemy import text

    from app.core.events_catalog import SYSTEM_STATUS
    from app.core.models import StatusAlert
    from app.core.outbox import enqueue
    from app.core.settings_store import get_int

    names = {row[1] for row in session.execute(text("PRAGMA table_info(status_alerts)")).all()}
    if "pending" not in names:
        session.execute(text("ALTER TABLE status_alerts ADD COLUMN pending TEXT NOT NULL DEFAULT ''"))
    fingerprint = "\n".join(lines)
    row = session.get(StatusAlert, 1)
    if row is None:
        row = StatusAlert(id=1, fingerprint="", pending="", notified_at=None)
        session.add(row)
        session.flush()
    now = utcnow()
    if fingerprint == (row.fingerprint or ""):
        row.pending = ""
        if not fingerprint or row.notified_at is None:
            return
        if (now - row.notified_at).total_seconds() < get_int("core", "watch.remind_hours") * 3600:
            return
        title = "В состоянии всё ещё не работает"
    elif not fingerprint:
        row.pending = ""
        if not row.fingerprint:
            return
        title = "Состояние снова в порядке"
        fingerprint = ""
    elif fingerprint != (row.pending or ""):
        row.pending = fingerprint
        session.flush()
        return
    else:
        title = "В состоянии что-то не работает"
    subject = "Проверка больше не находит поломок." if title.startswith("Состояние снова") else "\n".join(lines)
    enqueue(session, SYSTEM_STATUS, {"title": title, "subject": subject, "link": "/system"}, user_id=None)
    row.fingerprint = "" if title.startswith("Состояние снова") else "\n".join(lines)
    row.pending = ""
    row.notified_at = now
    session.flush()


