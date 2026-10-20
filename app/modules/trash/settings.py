from __future__ import annotations

from app.core.setting_defs import SettingDef


def _s(**kwargs) -> SettingDef:
    return SettingDef(module="trash", **kwargs)


DEFS: tuple[SettingDef, ...] = (
    _s(
        key="retention_days",
        value_type="int",
        default=30,
        label="Сколько дней запись лежит в корзине",
        description="Потом джоба очистки удаляет её окончательно.",
        ui_hint="number",
        min_value=1,
        max_value=3650,
    ),
    _s(
        key="purge.interval_seconds",
        value_type="int",
        default=3600,
        label="Как часто чистить корзину, сек",
        ui_hint="number",
        min_value=60,
        max_value=86400,
    ),
)
