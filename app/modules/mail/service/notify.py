"""Уведомления о почте: режимы, условия, CRUD правил уведомлений."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import log_scope, logger
from app.core.settings_store import get_bool, get_str, set_value
from app.modules.mail.models import MailMessage, MailNotifyRule, MailTag
from app.modules.mail.service._matching import _matches
from app.modules.mail.service._settings import _choice, _choices, _clean, _label
from app.modules.mail.service._tags import _tag_value_matches


def notify_state(session: Session) -> dict:
    rules = session.scalars(select(MailNotifyRule).order_by(MailNotifyRule.position, MailNotifyRule.id)).all()
    return {
        "mode": get_str("mail", "notify.mode"),
        "match": get_str("mail", "notify.match"),
        "gate_filed": get_bool("mail", "notify.gate_filed"),
        "modes": _choices(0, "notify.modes"),
        "matches": _choices(0, "notify.matches"),
        "fields": _choices(0, "notify.fields"),
        "ops": _choices(0, "notify.ops"),
        "rules": [_notify_rule_out(session, rule) for rule in rules],
    }


def save_notify(session: Session, user_id: int, fields: dict) -> dict:
    mode = _choice(str(fields.get("mode") or ""), 0, "notify.modes", "Неизвестный режим")
    match = _choice(str(fields.get("match") or ""), 0, "notify.matches", "Неизвестное сочетание условий")
    gate = fields.get("gate_filed")
    if not isinstance(gate, bool):
        raise HTTPException(status_code=400, detail="Укажите, фильтровать ли письма проекта")
    set_value("mail", "notify.mode", "global", mode, actor_id=user_id)
    set_value("mail", "notify.match", "global", match, actor_id=user_id)
    set_value("mail", "notify.gate_filed", "global", gate, actor_id=user_id)
    with log_scope("mail", "notify", user_id=user_id):
        logger.info("mail notify mode={} match={}", mode, match)
    return notify_state(session)


def create_notify_rule(session: Session, user_id: int, fields: dict) -> dict:
    field, op = _notify_pair(fields.get("field") or "", fields.get("op") or "")
    raw = str(fields.get("value") or "").strip()
    if field == "tag":
        value = _notify_tag_value(session, raw)
    else:
        value = _clean(raw, "rule.value.max_length", "Укажите значение условия")
    position = session.scalar(select(func.max(MailNotifyRule.position))) or 0
    session.add(MailNotifyRule(field=field, op=op, value=value, position=int(position) + 1))
    session.flush()
    with log_scope("mail", "notify.rule", user_id=user_id):
        logger.info("mail notify rule field={} op={}", field, op)
    return notify_state(session)


def delete_notify_rule(session: Session, user_id: int, rule_id: int) -> dict:
    row = session.get(MailNotifyRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Условие не найдено")
    session.delete(row)
    session.flush()
    with log_scope("mail", "notify.rule", user_id=user_id):
        logger.info("mail notify rule deleted id={}", rule_id)
    return notify_state(session)


def _letter_matches_notify(session: Session, row: MailMessage) -> bool:
    if get_str("mail", "notify.mode") != "filter":
        return True
    rules = list(session.scalars(select(MailNotifyRule).order_by(MailNotifyRule.position, MailNotifyRule.id)).all())
    if not rules:
        return False
    hits = [_notify_rule_matches(session, rule, row) for rule in rules]
    if get_str("mail", "notify.match") == "all":
        return all(hits)
    return any(hits)


def _filed_matches_notify(session: Session, row: MailMessage) -> bool:
    if not get_bool("mail", "notify.gate_filed"):
        return True
    return _letter_matches_notify(session, row)


def _notify_rule_matches(session: Session, rule: MailNotifyRule, row: MailMessage) -> bool:
    if rule.field == "tag":
        return _tag_value_matches(session, row, rule.op, rule.value)
    parsed = {
        "from_name": row.from_name or "",
        "from_addr": row.from_addr or "",
        "to_addr": row.to_addr or "",
        "subject": row.subject or "",
        "body": row.body or "",
    }
    return _matches(rule, parsed, get_bool("mail", "rules.casefold"))


def _notify_rule_out(session: Session, rule: MailNotifyRule) -> dict:
    shown = rule.value
    if rule.field == "tag" and str(rule.value).isdigit():
        tag = session.get(MailTag, int(rule.value))
        shown = tag.name if tag is not None else "хештег удалён"
    field_label = _label(0, "notify.fields", rule.field)
    op_label = _label(0, "notify.ops", rule.op)
    return {
        "id": rule.id,
        "field": rule.field,
        "op": rule.op,
        "value": rule.value,
        "text": field_label + " " + op_label + " «" + shown + "»",
    }


def _notify_pair(field: str, op: str) -> tuple[str, str]:
    field_code = _choice(field, 0, "notify.fields", "Поле не из списка")
    op_code = _choice(op, 0, "notify.ops", "Операция не из списка")
    if field_code == "tag" and op_code not in ("equals", "contains", "not_contains"):
        raise HTTPException(status_code=400, detail="Для хештега нужно равно, содержит или не содержит")
    return field_code, op_code


def _notify_tag_value(session: Session, raw: str) -> str:
    if raw.isdigit():
        tag = session.get(MailTag, int(raw))
        if tag is None:
            raise HTTPException(status_code=400, detail="Хештег не найден")
        return str(tag.id)
    name = _clean(raw, "tags.name.max_length", "Укажите хештег")
    tag = session.scalars(select(MailTag).where(MailTag.name == name)).first()
    if tag is None:
        raise HTTPException(status_code=400, detail="Такого хештега нет. Сначала создайте его на вкладке «Хештеги»")
    return str(tag.id)
