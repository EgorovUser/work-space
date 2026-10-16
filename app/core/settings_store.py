from __future__ import annotations

import copy
import json
import threading

from cryptography.fernet import Fernet
from sqlalchemy import delete, select

from app.core.config import get as get_config
from app.core.db import session_scope, utcnow
from app.core.logging import log_scope, logger
from app.core.models import SettingDefinitionRow, SettingValue
from app.core.setting_defs import SettingDef

_defs: dict[tuple[str, str], SettingDef] = {}
_cache: dict[tuple, object] = {}
_lock = threading.Lock()
_MISS = object()
_INVALID = object()


class SettingsError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def register_defs(defs: list[SettingDef] | tuple[SettingDef, ...]) -> None:
    for item in defs:
        _defs[(item.module, item.key)] = item


def definition(module: str, key: str) -> SettingDef:
    try:
        return _defs[(module, key)]
    except KeyError as exc:
        raise SettingsError("Неизвестная настройка") from exc


def definitions(module: str | None = None) -> list[SettingDef]:
    items = [item for item in _defs.values() if module is None or item.module == module]
    return sorted(items, key=lambda item: (item.module, item.key))


def sync_definitions() -> None:
    modules = {item.module for item in _defs.values()}
    with session_scope() as session:
        seen: set[tuple[str, str]] = set()
        for item in _defs.values():
            seen.add((item.module, item.key))
            row = session.get(SettingDefinitionRow, (item.module, item.key))
            fields = _row_fields(item)
            if row is None:
                session.add(SettingDefinitionRow(**fields))
            else:
                for name, value in fields.items():
                    setattr(row, name, value)
        if not modules:
            return
        existing = session.scalars(
            select(SettingDefinitionRow).where(SettingDefinitionRow.module.in_(modules))
        ).all()
        for row in existing:
            if (row.module, row.key) not in seen:
                session.execute(
                    delete(SettingValue).where(
                        SettingValue.module == row.module,
                        SettingValue.key == row.key,
                    )
                )
                session.delete(row)


def get(module: str, key: str, project_id: int | None = None, user_id: int | None = None):
    item = definition(module, key)
    cache_key = (
        module,
        key,
        project_id if "project" in item.allowed_scopes else None,
        user_id if "user" in item.allowed_scopes else None,
    )
    with _lock:
        cached = _cache.get(cache_key, _MISS)
    if cached is not _MISS and not item.secret:
        return _copy(cached)
    value = _resolve(item, project_id, user_id)
    if not item.secret:
        with _lock:
            _cache[cache_key] = value
    return _copy(value)


def get_int(module: str, key: str, project_id: int | None = None, user_id: int | None = None) -> int:
    value = get(module, key, project_id=project_id, user_id=user_id)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsError(module + "." + key + " не целое число")
    return value


def peek_secret(
    module: str,
    key: str,
    scope: str,
    *,
    user_id: int | None = None,
    project_id: int | None = None,
) -> str | None:
    item = definition(module, key)
    row_project, row_user = _scope_ids(scope, project_id, user_id)
    scope_key = _scope_key(scope, row_project, row_user)
    with session_scope() as session:
        value = _read(session, item, scope_key)
    if value is _MISS or not isinstance(value, str):
        return None
    return value


def get_str(module: str, key: str, project_id: int | None = None, user_id: int | None = None) -> str:
    value = get(module, key, project_id=project_id, user_id=user_id)
    if not isinstance(value, str):
        raise SettingsError(module + "." + key + " не строка")
    return value


def get_bool(module: str, key: str, project_id: int | None = None, user_id: int | None = None) -> bool:
    value = get(module, key, project_id=project_id, user_id=user_id)
    if not isinstance(value, bool):
        raise SettingsError(module + "." + key + " не логическое значение")
    return value


def set_value(
    module: str,
    key: str,
    scope: str,
    value,
    *,
    actor_id: int | None,
    project_id: int | None = None,
    user_id: int | None = None,
) -> None:
    item = definition(module, key)
    if scope not in item.allowed_scopes:
        raise SettingsError("Эта настройка не задаётся в выбранной области")
    row_project, row_user = _scope_ids(scope, project_id, user_id if scope == "user" else actor_id)
    if item.secret:
        if not isinstance(value, str) or value == "":
            raise SettingsError("Секрет нельзя сохранить пустым. Чтобы убрать его, сбросьте настройку")
        if item.module == "notifications" and item.key == "telegram.bot_token":
            from app.modules.notifications.token import normalize_bot_token

            cleaned = normalize_bot_token(value)
            if not cleaned:
                raise SettingsError(
                    "Это не токен бота. Скопируйте его из BotFather целиком: число, двоеточие и длинный ключ, без пробелов."
                )
            value = cleaned
        stored = json.dumps(_fernet().encrypt(value.encode("utf-8")).decode("ascii"))
        shown = "***"
    else:
        coerced = _coerce(item, value)
        stored = json.dumps(coerced, ensure_ascii=False)
        shown = _short(coerced)
    scope_key = _scope_key(scope, row_project, row_user)
    with session_scope() as session:
        row = _find(session, module, key, scope_key)
        if row is None:
            session.add(
                SettingValue(
                    module=module,
                    key=key,
                    scope_key=scope_key,
                    scope=scope,
                    project_id=row_project,
                    user_id=row_user,
                    value_json=stored,
                    updated_by=actor_id,
                    updated_at=utcnow(),
                )
            )
        else:
            row.value_json = stored
            row.updated_by = actor_id
            row.updated_at = utcnow()
    _invalidate(module, key)
    with log_scope("settings", "set", user_id=actor_id):
        logger.info("setting set module={} key={} scope={} value={}", module, key, scope_key, shown)
    if module == "core" and key in ("logs.rotation_mb", "logs.retention_days"):
        _reconfigure_logs()


def reset_value(
    module: str,
    key: str,
    scope: str,
    *,
    actor_id: int | None,
    project_id: int | None = None,
    user_id: int | None = None,
) -> None:
    item = definition(module, key)
    if scope not in item.allowed_scopes:
        raise SettingsError("Эта настройка не задаётся в выбранной области")
    row_project, row_user = _scope_ids(scope, project_id, user_id if scope == "user" else actor_id)
    scope_key = _scope_key(scope, row_project, row_user)
    with session_scope() as session:
        session.execute(
            delete(SettingValue).where(
                SettingValue.module == module,
                SettingValue.key == key,
                SettingValue.scope_key == scope_key,
            )
        )
    _invalidate(module, key)
    with log_scope("settings", "reset", user_id=actor_id):
        logger.info("setting reset module={} key={} scope={}", module, key, scope_key)
    if module == "core" and key in ("logs.rotation_mb", "logs.retention_days"):
        _reconfigure_logs()


def override_state(
    item: SettingDef,
    scope: str,
    *,
    project_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    row_project, row_user = _scope_ids(scope, project_id, user_id)
    scope_key = _scope_key(scope, row_project, row_user)
    with session_scope() as session:
        row = _find(session, item.module, item.key, scope_key)
        if row is None:
            return {
                "value": None if item.secret else _copy(item.default),
                "is_override": False,
                "is_set": False,
            }
        if item.secret:
            return {"value": None, "is_override": True, "is_set": True}
        decoded = _decode(item, row.value_json)
        if decoded is _INVALID:
            return {"value": _copy(item.default), "is_override": True, "is_set": True}
        return {"value": _copy(decoded), "is_override": True, "is_set": True}


def effective_values(user_id: int | None, project_id: int | None) -> dict:
    result: dict[str, dict] = {}
    for item in definitions():
        if item.secret:
            continue
        result.setdefault(item.module, {})[item.key] = get(
            item.module, item.key, project_id=project_id, user_id=user_id
        )
    return result


def public_values() -> dict:
    values = {}
    for item in definitions():
        if item.public and not item.secret:
            values[item.module + "." + item.key] = get(item.module, item.key)
    return values


def healthcheck() -> None:
    get("core", "ui.app_title")


def _resolve(item: SettingDef, project_id: int | None, user_id: int | None):
    with session_scope() as session:
        if user_id is not None and "user" in item.allowed_scopes:
            value = _read(session, item, _scope_key("user", None, user_id))
            if value is not _MISS:
                return value
        if project_id is not None and "project" in item.allowed_scopes:
            value = _read(session, item, _scope_key("project", project_id, None))
            if value is not _MISS:
                return value
        if "global" in item.allowed_scopes:
            value = _read(session, item, "global")
            if value is not _MISS:
                return value
    return _copy(item.default)


def _read(session, item: SettingDef, scope_key: str):
    row = _find(session, item.module, item.key, scope_key)
    if row is None:
        return _MISS
    decoded = _decode(item, row.value_json)
    if decoded is _INVALID:
        return _MISS
    return decoded


def _decode(item: SettingDef, raw: str):
    try:
        value = json.loads(raw)
        if item.secret:
            if not isinstance(value, str) or value == "":
                return _INVALID
            return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
        return _coerce(item, value)
    except Exception:
        with log_scope("settings", "read"):
            logger.warning("setting ignored module={} key={}", item.module, item.key)
        return _INVALID


def _coerce(item: SettingDef, value):
    kind = item.value_type
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingsError("Ожидается целое число")
        _check_range(item, value)
        return value
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingsError("Ожидается число")
        number = float(value)
        _check_range(item, number)
        return number
    if kind == "bool":
        if not isinstance(value, bool):
            raise SettingsError("Ожидается да или нет")
        return value
    if kind == "str":
        if not isinstance(value, str):
            raise SettingsError("Ожидается строка")
        if item.options and value not in item.options:
            raise SettingsError("Значение не из списка")
        return value
    if kind == "json":
        json.dumps(value)
        return value
    raise SettingsError("Неизвестный тип настройки")


def _check_range(item: SettingDef, number: float) -> None:
    if item.min_value is not None and number < item.min_value:
        raise SettingsError("Значение меньше допустимого")
    if item.max_value is not None and number > item.max_value:
        raise SettingsError("Значение больше допустимого")


def _scope_ids(scope: str, project_id: int | None, user_id: int | None) -> tuple[int | None, int | None]:
    if scope == "global":
        return None, None
    if scope == "project":
        if not project_id:
            raise SettingsError("Нужен project_id")
        from app.core.deps import ensure_project

        ensure_project(project_id)
        return project_id, None
    if scope == "user":
        if not user_id:
            raise SettingsError("Нужен пользователь")
        return None, user_id
    raise SettingsError("Неизвестная область")


def _scope_key(scope: str, project_id: int | None, user_id: int | None) -> str:
    if scope == "global":
        return "global"
    if scope == "project":
        return "project:" + str(project_id)
    if scope == "user":
        return "user:" + str(user_id)
    raise SettingsError("Неизвестная область")


def _find(session, module: str, key: str, scope_key: str) -> SettingValue | None:
    return session.scalars(
        select(SettingValue).where(
            SettingValue.module == module,
            SettingValue.key == key,
            SettingValue.scope_key == scope_key,
        )
    ).one_or_none()


def _row_fields(item: SettingDef) -> dict:
    return {
        "module": item.module,
        "key": item.key,
        "value_type": item.value_type,
        "default_json": json.dumps(item.default, ensure_ascii=False),
        "allowed_scopes": json.dumps(list(item.allowed_scopes)),
        "label": item.label,
        "description": item.description,
        "ui_hint": item.ui_hint,
        "options_json": json.dumps(list(item.options)) if item.options else None,
        "secret": item.secret,
        "is_public": item.public,
        "restart_required": item.restart_required,
        "min_value": item.min_value,
        "max_value": item.max_value,
    }


def _fernet() -> Fernet:
    return Fernet(get_config().fernet_key.encode("ascii"))


def _invalidate(module: str, key: str) -> None:
    with _lock:
        for cache_key in [item for item in _cache if item[0] == module and item[1] == key]:
            _cache.pop(cache_key, None)


def _copy(value):
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    return value


def _short(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) > 180:
        return text[:180] + "…"
    return text


def _reconfigure_logs() -> None:
    try:
        from app.core.logging import apply_settings

        apply_settings()
    except Exception:
        with log_scope("settings", "logs.reconfigure"):
            logger.exception("log reconfigure failed")
