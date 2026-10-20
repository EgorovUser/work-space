"""Роутер почты, разбитый на тематические файлы.

Путь модуля ``app.modules.mail.router`` сохранён (файл стал пакетом),
поэтому ``from app.modules.mail.router import setup`` в app/modules не
меняется. Сборка одного APIRouter из под-роутеров:

- ``schemas.py`` — схемы входов (ящики, правила, письма, метки);
- ``mailbox.py`` — общий ящик /api/mail*;
- ``project.py`` — почта проекта /api/projects/{id}/mail*.

Здесь — сборка и регистрация моста/джоб в setup(app).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.bridge import register_card, register_dashboard, register_inbox, register_search
from app.core.counters import register_global_counters, register_project_counters
from app.modules.mail.service import counters as counters_service
from app.core.scheduler import register_job
from app.core.settings_store import register_defs
from app.modules.mail import service
from app.modules.mail.router import mailbox as mailbox_routes
from app.modules.mail.router import project as project_routes
from app.modules.mail.settings import DEFS

router = APIRouter()
router.include_router(mailbox_routes.router)
router.include_router(project_routes.router)


def setup(app) -> None:
    service.ensure_schema()
    register_defs(DEFS)
    register_global_counters("mail", counters_service.global_counts)
    register_project_counters("mail", counters_service.project_counts)
    register_card("mail", service.card_provider)
    register_inbox("mail", service.inbox_provider)
    register_inbox("events", service.events_today)
    register_dashboard("mail", service.dashboard_provider)
    register_search("mail", service.search_provider)
    register_job(
        "mail.poll",
        service.poll_accounts,
        module="mail",
        action="poll",
        interval_module="mail",
        interval_key="job.seconds",
        label="Забор почты",
        detail="Новые и ещё не скачанные письма",
        enabled_module="mail",
        enabled_key="job.enabled",
    )
    register_job(
        "mail.events",
        service.remind_events,
        module="mail",
        action="events",
        interval_module="mail",
        interval_key="events.check_seconds",
        label="События из почты",
        detail="Напоминания «сегодня» и «скоро»",
        enabled_module="mail",
        enabled_key="events.remind",
    )
    app.include_router(router)
