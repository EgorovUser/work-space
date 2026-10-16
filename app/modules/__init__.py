"""Бизнес-модули. Список пополняется по мере реализации."""

from __future__ import annotations


def import_models() -> None:
    from app.core.logging import logger

    for name in (
        "app.modules.projects.models",
        "app.modules.tasks.models",
        "app.modules.documents.models",
        "app.modules.examples.models",
        "app.modules.secrets.models",
        "app.modules.timetracking.models",
        "app.modules.mail.models",
        "app.modules.notifications.models",
    ):
        try:
            __import__(name)
        except Exception:
            logger.exception("model import failed module={}", name)


def setup_modules(app) -> None:
    from app.core.registry import try_register
    from app.core.settings_store import sync_definitions
    from app.modules.documents.router import setup as setup_documents
    from app.modules.examples.router import setup as setup_examples
    from app.modules.mail.router import setup as setup_mail
    from app.modules.notifications.router import setup as setup_notifications
    from app.modules.projects.router import setup as setup_projects
    from app.modules.secrets.router import setup as setup_secrets
    from app.modules.tasks.router import setup as setup_tasks
    from app.modules.timetracking.router import setup as setup_timetracking

    modules = (
        ("projects", setup_projects),
        ("tasks", setup_tasks),
        ("documents", setup_documents),
        ("examples", setup_examples),
        ("secrets", setup_secrets),
        ("timetracking", setup_timetracking),
        ("mail", setup_mail),
        ("notifications", setup_notifications),
    )
    for name, setup in modules:
        try_register(name, lambda app=app, setup=setup: setup(app))
    sync_definitions()
