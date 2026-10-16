from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.auth import require_user
from app.core.models import User
from app.core.settings_store import (
    SettingsError,
    definition,
    definitions,
    effective_values,
    override_state,
    public_values,
    reset_value,
    set_value,
)

router = APIRouter()


class SettingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    key: str
    scope: str
    project_id: int | None = None
    value: Any = None


class SettingReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    key: str
    scope: str
    project_id: int | None = None


@router.get("/api/settings/bootstrap")
def bootstrap() -> dict:
    return {"values": public_values()}


@router.get("/api/settings/effective")
def effective(project_id: int | None = None, user: User = Depends(require_user)) -> dict:
    return effective_values(user.id, project_id)


@router.get("/api/settings")
def list_settings(
    module: str | None = None,
    project_id: int | None = None,
    user: User = Depends(require_user),
) -> dict:
    return {"items": [_payload(item, user.id, project_id) for item in definitions(module)]}


@router.put("/api/settings")
def put_setting(body: SettingWrite, user: User = Depends(require_user)) -> dict:
    try:
        set_value(
            body.module,
            body.key,
            body.scope,
            body.value,
            actor_id=user.id,
            project_id=body.project_id,
            user_id=user.id,
        )
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return _payload(definition(body.module, body.key), user.id, body.project_id)


@router.post("/api/settings/reset")
def reset_setting(body: SettingReset, user: User = Depends(require_user)) -> dict:
    try:
        reset_value(
            body.module,
            body.key,
            body.scope,
            actor_id=user.id,
            project_id=body.project_id,
            user_id=user.id,
        )
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return _payload(definition(body.module, body.key), user.id, body.project_id)


def _payload(item, user_id: int, project_id: int | None) -> dict:
    values: dict[str, dict] = {}
    if "global" in item.allowed_scopes:
        values["global"] = override_state(item, "global")
    if "user" in item.allowed_scopes:
        values["user"] = override_state(item, "user", user_id=user_id)
    if "project" in item.allowed_scopes and project_id is not None:
        values["project"] = override_state(item, "project", project_id=project_id)
    if item.module == "notifications" and item.key == "telegram.bot_token":
        _mark_bot_token(values, user_id, project_id)
    return {
        "module": item.module,
        "key": item.key,
        "value_type": item.value_type,
        "label": item.label,
        "description": item.description,
        "ui_hint": item.ui_hint,
        "options": list(item.options) if item.options else None,
        "secret": item.secret,
        "public": item.public,
        "restart_required": item.restart_required,
        "min_value": item.min_value,
        "max_value": item.max_value,
        "allowed_scopes": list(item.allowed_scopes),
        "default": None if item.secret else item.default,
        "values": values,
    }


def _mark_bot_token(values: dict, user_id: int, project_id: int | None) -> None:
    from app.core.settings_store import peek_secret
    from app.modules.notifications.token import normalize_bot_token

    for scope, state in values.items():
        if not state.get("is_set"):
            state["usable"] = False
            continue
        raw = peek_secret(
            "notifications",
            "telegram.bot_token",
            scope,
            user_id=user_id,
            project_id=project_id,
        )
        state["usable"] = bool(raw and normalize_bot_token(raw))

