"""Схемы входов почтовых эндпоинтов: ящики, правила, письма, метки, уведомления."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    port: int | None = None
    use_ssl: bool | None = None
    username: str = ""
    password: str = ""
    folder: str = ""
    enabled: bool | None = None


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    host: str | None = None
    port: int | None = None
    use_ssl: bool | None = None
    username: str | None = None
    password: str | None = None
    folder: str | None = None
    enabled: bool | None = None


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    field: str
    op: str
    value: str
    action: str
    enabled: bool | None = None


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    field: str | None = None
    op: str | None = None
    value: str | None = None
    action: str | None = None
    enabled: bool | None = None


class MessagePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: bool | None = None
    archived: bool | None = None


class FolderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int | None = None
    move: bool = False


class DocumentTarget(BaseModel):
    """Куда положить документ из вложения (общий ящик)."""

    model_config = ConfigDict(extra="forbid")

    project_id: int


class TagRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    op: str
    value: str


class TagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    color: str
    rules: list[TagRuleIn] = []


class TagAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_id: int
    on: bool


class NotifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    match: str
    gate_filed: bool


class NotifyRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    op: str
    value: str
