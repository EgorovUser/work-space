"""Фасад сервиса конфигураций страниц (патч AW).

- ``store.py``     — хранение, ревизии, сигнал вкладкам;
- ``normalize.py`` — whitelist-нормализация по каталогу.
"""

from app.modules.ui.service.normalize import configs_equal, normalize_items, normalize_settings
from app.modules.ui.service.store import (
    UI_CHANGED,
    default_items,
    default_settings,
    list_revisions,
    page_state,
    reset_config,
    restore_revision,
    save_config,
)

__all__ = [
    "UI_CHANGED",
    "configs_equal",
    "default_items",
    "default_settings",
    "list_revisions",
    "normalize_items",
    "normalize_settings",
    "page_state",
    "reset_config",
    "restore_revision",
    "save_config",
]
