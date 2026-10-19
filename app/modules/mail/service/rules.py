"""Правила раскладки писем по проектам: CRUD с переприменением к существующим."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.logging import log_scope, logger
from app.modules.mail.models import MailRule
from app.modules.mail.service._queries import _rule
from app.modules.mail.service._serialize import _rule_out
from app.modules.mail.service._settings import _choice, _clean
from app.modules.mail.service.accounts import _run_moves
from app.modules.mail.service.ingest import _file_project
from app.modules.projects.service import touch_project


def create_rule(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    position = session.scalar(select(func.max(MailRule.position)).where(MailRule.project_id == project_id)) or 0
    row = MailRule(
        project_id=project_id,
        name=_clean(fields.get("name") or "", "rule.name.max_length", "Укажите название"),
        enabled=True if fields.get("enabled") is None else bool(fields.get("enabled")),
        position=int(position) + 1,
        field=_choice(fields.get("field") or "", project_id, "rules.fields", "Поле не из списка"),
        op=_choice(fields.get("op") or "", project_id, "rules.ops", "Операция не из списка"),
        value=_clean(fields.get("value") or "", "rule.value.max_length", "Укажите значение"),
        action="keep",
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    moves: list[tuple[int, str, int | None]] = []
    _file_project(session, project_id, user_id, moves)
    session.commit()
    _run_moves(moves)
    with log_scope("mail", "rule.create", user_id=user_id):
        logger.info("mail rule id={}", row.id)
    return _rule_out(row, project_id)


def update_rule(session: Session, project_id: int, user_id: int, rule_id: int, fields: dict) -> dict:
    row = _rule(session, project_id, rule_id)
    if "name" in fields and fields["name"] is not None:
        row.name = _clean(fields["name"], "rule.name.max_length", "Укажите название")
    if "enabled" in fields and fields["enabled"] is not None:
        row.enabled = bool(fields["enabled"])
    if "field" in fields and fields["field"] is not None:
        row.field = _choice(fields["field"], project_id, "rules.fields", "Поле не из списка")
    if "op" in fields and fields["op"] is not None:
        row.op = _choice(fields["op"], project_id, "rules.ops", "Операция не из списка")
    if "value" in fields and fields["value"] is not None:
        row.value = _clean(fields["value"], "rule.value.max_length", "Укажите значение")
    touch_project(session, project_id)
    session.flush()
    with log_scope("mail", "rule.update", user_id=user_id):
        logger.info("mail rule updated id={}", row.id)
    return _rule_out(row, project_id)


def delete_rule(session: Session, project_id: int, user_id: int, rule_id: int) -> None:
    row = _rule(session, project_id, rule_id)
    session.delete(row)
    touch_project(session, project_id)
    session.flush()
    with log_scope("mail", "rule.delete", user_id=user_id):
        logger.info("mail rule deleted id={}", rule_id)
