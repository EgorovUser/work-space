from __future__ import annotations

from app.core.setting_defs import SettingDef


def _s(**kwargs) -> SettingDef:
    return SettingDef(module="ui", **kwargs)


DEFS: tuple[SettingDef, ...] = (
    _s(
        key="history.keep_revisions",
        value_type="int",
        default=10,
        label="Сколько снимков конфигурации страниц хранить",
        description="Глубина истории «Вернуть» в редакторе страницы: каждое реальное изменение сохраняет снимок прежнего состояния.",
        ui_hint="number",
        min_value=1,
        max_value=100,
    ),
)
