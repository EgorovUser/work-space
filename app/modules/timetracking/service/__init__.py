"""Сервис учёта времени, разбитый на тематические файлы.

Публичный API реэкспортируется отсюда целиком, поэтому внешние импорты
(``from app.modules.timetracking import service`` в router.py) не меняются.

Раскладка по файлам:

- ``_shared.py`` — зона, даты, сериализация записей: общее для всех слоёв;
- ``entries.py`` — ручные записи: создание, правка, удаление;
- ``timer.py``  — таймер: старт, стоп, автостоп джобой;
- ``report.py`` — страница проекта: лента, отчёт, карточка, дашборд;
- ``overview.py`` — глобальная сводка по всем проектам (патч S).
"""

from app.modules.timetracking.service.entries import create_entry, delete_entry, update_entry
from app.modules.timetracking.service.overview import overview
from app.modules.timetracking.service.report import card_provider, dashboard_provider, project_time
from app.modules.timetracking.service.timer import (
    autostop_open,
    notify_hours_open,
    running_for_user,
    start_timer,
    stop_timer,
    stop_timer_anywhere,
)

__all__ = [
    "autostop_open",
    "card_provider",
    "create_entry",
    "dashboard_provider",
    "delete_entry",
    "notify_hours_open",
    "overview",
    "project_time",
    "running_for_user",
    "start_timer",
    "stop_timer",
    "stop_timer_anywhere",
    "update_entry",
]
