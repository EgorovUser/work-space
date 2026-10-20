from __future__ import annotations

from app.core.setting_defs import SettingDef


def _s(**kwargs) -> SettingDef:
    return SettingDef(module="rdp", **kwargs)


DEFS: tuple[SettingDef, ...] = (
    _s(
        key="name.max_length",
        value_type="int",
        default=200,
        label="Максимальная длина названия",
        ui_hint="number",
        min_value=1,
        max_value=1000,
    ),
    _s(
        key="host.max_length",
        value_type="int",
        default=255,
        label="Максимальная длина адреса",
        ui_hint="number",
        min_value=1,
        max_value=1000,
    ),
    _s(
        key="username.max_length",
        value_type="int",
        default=200,
        label="Максимальная длина логина",
        ui_hint="number",
        min_value=0,
        max_value=1000,
    ),
    _s(
        key="domain.max_length",
        value_type="int",
        default=200,
        label="Максимальная длина домена",
        ui_hint="number",
        min_value=0,
        max_value=1000,
    ),
    _s(
        key="note.max_length",
        value_type="int",
        default=5000,
        label="Максимальная длина заметки",
        ui_hint="number",
        min_value=0,
        max_value=100000,
    ),
    _s(
        key="port.default",
        value_type="int",
        default=3389,
        label="Порт по умолчанию",
        description="Подставляется в форму нового подключения.",
        allowed_scopes=("global", "project"),
        ui_hint="number",
        min_value=1,
        max_value=65535,
    ),
    _s(
        key="list.limit",
        value_type="int",
        default=100,
        label="Подключений в списке",
        allowed_scopes=("global", "project"),
        ui_hint="number",
        min_value=1,
        max_value=5000,
    ),
    _s(
        key="list.scan_limit",
        value_type="int",
        default=1000,
        label="Сколько записей просматривать при фильтре",
        allowed_scopes=("global", "project"),
        ui_hint="number",
        min_value=1,
        max_value=20000,
    ),
    _s(
        key="search.include_archived",
        value_type="bool",
        default=False,
        label="Искать в архивных подключениях",
        description="Ищутся название и адрес сервера.",
        allowed_scopes=("global", "project"),
        ui_hint="checkbox",
    ),
)
