"""Хештеги писем: каталог, правила, закрепления/скрытия, раскраска списков."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.logging import log_scope, logger
from app.core.settings_store import get_str
from app.modules.mail.models import (
    MailMessage,
    MailTag,
    MailTagHide,
    MailTagPin,
    MailTagRule,
)
from app.modules.mail.service._matching import _matches
from app.modules.mail.service._settings import _choice, _choices, _clean, _zone


def tag_page(session: Session) -> dict:
    return {
        "tags": _tag_catalog(session),
        "tag_fields": _choices(0, "tags.fields"),
        "tag_ops": _choices(0, "tags.ops"),
        "tag_default_color": get_str("mail", "tags.default_color"),
    }


def create_tag(session: Session, user_id: int, fields: dict) -> dict:
    name = _clean(fields.get("name") or "", "tags.name.max_length", "Укажите название хештега")
    color = _tag_color(fields.get("color") or "")
    raw_rules = fields.get("rules") or []
    if not isinstance(raw_rules, list) or not any(isinstance(item, dict) and str(item.get("value") or "").strip() for item in raw_rules):
        raise HTTPException(status_code=400, detail="Нужно хотя бы одно условие: вручную хештег на письмо больше не ставится")
    position = session.scalar(select(func.max(MailTag.position))) or 0
    tag = MailTag(name=name, color=color, enabled=True, position=int(position) + 1, created_at=utcnow())
    session.add(tag)
    session.flush()
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        field, op = _tag_pair(item.get("field") or "", item.get("op") or "")
        value = _clean(item.get("value") or "", "rule.value.max_length", "Укажите значение условия")
        if field == "received":
            try:
                value = datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Дата в виде ГГГГ-ММ-ДД") from exc
        session.add(MailTagRule(tag_id=tag.id, field=field, op=op, value=value))
    session.flush()
    with log_scope("mail", "tag.create", user_id=user_id):
        logger.info("mail tag id={}", tag.id)
    return _tag_out(session, tag)


def delete_tag(session: Session, user_id: int, tag_id: int) -> None:
    tag = session.get(MailTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Хештег не найден")
    session.delete(tag)
    session.flush()
    with log_scope("mail", "tag.delete", user_id=user_id):
        logger.info("mail tag deleted id={}", tag_id)


def _tag_value_matches(session: Session, row: MailMessage, op: str, value: str) -> bool:
    names, ids = _row_tag_keys(session, row)
    needle = (value or "").strip()
    folded = needle.casefold()
    blob = " ".join(sorted(names))
    if op == "equals":
        return folded in names or needle in ids
    if op == "not_contains":
        return folded not in blob and needle not in ids
    return folded in blob or needle in ids


def _row_tag_keys(session: Session, row: MailMessage) -> tuple[set[str], set[str]]:
    tags = list(session.scalars(select(MailTag).where(MailTag.enabled.is_(True))).all())
    if not tags:
        return set(), set()
    rules = list(session.scalars(select(MailTagRule).where(MailTagRule.tag_id.in_([tag.id for tag in tags]))).all())
    by_tag: dict[int, list[MailTagRule]] = {}
    for rule in rules:
        by_tag.setdefault(rule.tag_id, []).append(rule)
    pins = {(item.tag_id) for item in session.scalars(select(MailTagPin).where(MailTagPin.message_id == row.id)).all()}
    hides = {(item.tag_id) for item in session.scalars(select(MailTagHide).where(MailTagHide.message_id == row.id)).all()}
    names: set[str] = set()
    ids: set[str] = set()
    for tag in tags:
        if tag.id in hides:
            continue
        auto = bool(by_tag.get(tag.id)) and all(_tag_rule_matches(item, row) for item in by_tag[tag.id])
        if auto or tag.id in pins:
            names.add((tag.name or "").casefold())
            ids.add(str(tag.id))
    return names, ids


def _attach_tags(session: Session, messages: list[dict]) -> None:
    ids: list[int] = []
    for item in messages:
        ids.extend(item.get("thread_ids") or [item.get("id")])
    ids = [item for item in ids if item]
    if not ids:
        return
    tags = list(session.scalars(select(MailTag).where(MailTag.enabled.is_(True)).order_by(MailTag.position, MailTag.id)).all())
    rules = list(session.scalars(select(MailTagRule).where(MailTagRule.tag_id.in_([tag.id for tag in tags] or [0]))).all()) if tags else []
    by_tag: dict[int, list[MailTagRule]] = {}
    for rule in rules:
        by_tag.setdefault(rule.tag_id, []).append(rule)
    pins = session.scalars(select(MailTagPin).where(MailTagPin.message_id.in_(ids))).all()
    hides = session.scalars(select(MailTagHide).where(MailTagHide.message_id.in_(ids))).all()
    pin_set = {(item.message_id, item.tag_id) for item in pins}
    hide_set = {(item.message_id, item.tag_id) for item in hides}
    rows = {row.id: row for row in session.scalars(select(MailMessage).where(MailMessage.id.in_(ids))).all()}

    def chosen_for(message_id: int) -> list[dict]:
        row = rows.get(message_id)
        if row is None:
            return []
        chosen = []
        for tag in tags:
            auto = bool(by_tag.get(tag.id)) and all(_tag_rule_matches(rule, row) for rule in by_tag[tag.id])
            pinned = (row.id, tag.id) in pin_set
            hidden = (row.id, tag.id) in hide_set
            if hidden:
                continue
            if auto or pinned:
                chosen.append({"id": tag.id, "name": tag.name, "color": tag.color})
        return chosen

    for message in messages:
        member_ids = message.get("thread_ids") or [message.get("id")]
        seen: set[int] = set()
        chosen = []
        for member_id in member_ids:
            for tag in chosen_for(member_id):
                if tag["id"] in seen:
                    continue
                seen.add(tag["id"])
                chosen.append(tag)
        message["tags"] = chosen
        message.pop("thread_ids", None)


def _tag_rule_matches(rule: MailTagRule, row: MailMessage) -> bool:
    if rule.field == "received":
        local = row.received_at.astimezone(_zone()).date()
        try:
            day = datetime.strptime((rule.value or "")[:10], "%Y-%m-%d").date()
        except ValueError:
            return False
        if rule.op == "before":
            return local < day
        if rule.op == "after":
            return local > day
        return local == day
    parsed = {
        "from_name": row.from_name or "",
        "from_addr": row.from_addr or "",
        "to_addr": row.to_addr or "",
        "subject": row.subject or "",
        "body": row.body or "",
    }
    return _matches(rule, parsed, True)


def _tag_catalog(session: Session) -> list[dict]:
    tags = session.scalars(select(MailTag).order_by(MailTag.position, MailTag.id)).all()
    return [_tag_out(session, tag) for tag in tags]


def _tag_out(session: Session, tag: MailTag) -> dict:
    rules = session.scalars(select(MailTagRule).where(MailTagRule.tag_id == tag.id).order_by(MailTagRule.id)).all()
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "enabled": bool(tag.enabled),
        "rules": [{"field": rule.field, "op": rule.op, "value": rule.value} for rule in rules],
    }


def _tag_color(value: str) -> str:
    text_value = (value or "").strip()
    if not text_value:
        text_value = get_str("mail", "tags.default_color")
    if len(text_value) == 4 and text_value.startswith("#"):
        text_value = "#" + "".join(ch * 2 for ch in text_value[1:])
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", text_value):
        raise HTTPException(status_code=400, detail="Цвет задаётся как HEX, например #3a6ea5")
    return text_value.lower()


def _tag_pair(field: str, op: str) -> tuple[str, str]:
    field_code = _choice(field, 0, "tags.fields", "Поле не из списка")
    op_code = _choice(op, 0, "tags.ops", "Операция не из списка")
    date_ops = {"before", "after", "on"}
    if field_code == "received" and op_code not in date_ops:
        raise HTTPException(status_code=400, detail="Для даты нужны условия раньше, позже или в этот день")
    if field_code != "received" and op_code in date_ops:
        raise HTTPException(status_code=400, detail="Дата сравнивается только с полем даты")
    return field_code, op_code
