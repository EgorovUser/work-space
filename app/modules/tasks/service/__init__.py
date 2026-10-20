"""Сервис задач, разбитый на тематические файлы.

Публичный API реэкспортируется отсюда целиком, поэтому внешние импорты
не меняются:

- ``from app.modules.tasks import service`` (router.py, тесты) —
  ``service.list_tasks`` и прочие имена работают как раньше;
- ``from app.modules.tasks.service import get_task`` (timetracking) —
  тоже работает.

Раскладка по файлам:

- ``_queries.py``    — приватные выборки строк, батч-хелперы для доски;
- ``_validators.py`` — валидация входов (строки, приоритет, дедлайн, зона);
- ``_serialize.py``  — построение dict-ответов (brief/full/out-хелперы);
- ``statuses.py``    — колонки доски: сид, CRUD, порядок;
- ``tags.py``        — метки задач;
- ``board.py``       — задачи: батчевый список доски, CRUD, порядок;
- ``content.py``     — чеклист, комментарии, вложения;
- ``providers.py``   — карточка/инбокс/дашборд/поиск + джоба дедлайнов;
- ``search.py``      — поиск открытых задач для выбора в помодоро.
"""

from app.modules.tasks.service.board import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    load_task,
    order_tasks,
    update_task,
)
from app.modules.tasks.service.content import (
    add_attachment,
    add_check,
    add_comment,
    delete_attachment,
    delete_check,
    order_checks,
    update_check,
)
from app.modules.tasks.service.providers import (
    card_provider,
    check_deadlines,
    dashboard_provider,
    inbox_provider,
    search_provider,
)
from app.modules.tasks.service.search import clamp_limit, search_tasks
from app.modules.tasks.service.statuses import (
    backfill_statuses,
    create_status,
    delete_status,
    list_statuses,
    order_statuses,
    seed_project,
    seed_project_id,
    update_status,
)
from app.modules.tasks.service.tags import create_tag, delete_tag, list_tags

__all__ = [
    "add_attachment",
    "add_check",
    "add_comment",
    "backfill_statuses",
    "card_provider",
    "check_deadlines",
    "create_tag",
    "create_status",
    "create_task",
    "dashboard_provider",
    "delete_attachment",
    "delete_check",
    "delete_status",
    "delete_tag",
    "delete_task",
    "get_task",
    "inbox_provider",
    "list_statuses",
    "list_tags",
    "list_tasks",
    "load_task",
    "order_checks",
    "order_statuses",
    "order_tasks",
    "clamp_limit",
    "search_provider",
    "search_tasks",
    "seed_project",
    "seed_project_id",
    "update_check",
    "update_status",
    "update_task",
]
