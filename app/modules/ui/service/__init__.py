"""Фасад сервиса конфигураций страниц (патч AW).

- ``store.py``     — хранение, ревизии, сигнал вкладкам;
- ``normalize.py`` — whitelist-нормализация по каталогу.
"""

from app.modules.ui.service.normalize import items_equal, normalize_items
from app.modules.ui.service.store import (
    UI_CHANGED,
    default_items,
    list_revisions,
    page_state,
    reset_config,
    restore_revision,
    save_config,
)

__all__ = [
    "UI_CHANGED",
    "default_items",
    "items_equal",
    "list_revisions",
    "normalize_items",
    "page_state",
    "reset_config",
    "restore_revision",
    "save_config",
]
