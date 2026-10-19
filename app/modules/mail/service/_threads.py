"""Треды: свёртка тем, группировка писем, выдача цепочки письма."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.core.settings_store import get, get_bool, get_int
from app.modules.mail.models import MailMessage
from app.modules.mail.service._matching import _row_matches
from app.modules.mail.service._queries import _rules
from app.modules.mail.service._serialize import _message_out, _meta, _title


def _grouped_messages(session: Session, rows: list[MailMessage], project_id: int | None) -> list[dict]:
    groups: dict[str, list[MailMessage]] = {}
    order: list[str] = []
    for row in rows:
        key = _subject_key(row.subject, row.id, project_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    result = []
    for key in order:
        members = groups[key]
        latest = max(members, key=lambda item: (item.received_at, item.id))
        payload = _message_out(session, latest, full=False)
        cleaned = _clean_subject(latest.subject, project_id)
        if cleaned:
            payload["title"] = cleaned
        payload["thread_count"] = len(members)
        payload["thread_unread"] = sum(1 for item in members if not item.read)
        payload["thread_ids"] = [item.id for item in members]
        payload["attachment_count"] = sum(len(_meta(item)) for item in members)
        if payload["thread_unread"]:
            payload["read"] = False
        result.append(payload)
    result.sort(key=lambda item: item.get("received_at") or "", reverse=True)
    return result


def _thread_out(session: Session, row: MailMessage, project_id: int) -> tuple[list[dict], int]:
    scope = project_id or None
    if not get_bool("mail", "threads.enabled", project_id=scope):
        return [], 0
    key = _subject_key(row.subject, row.id, project_id)
    limit = get_int("mail", "threads.scan_limit", project_id=scope)
    rows = list(
        session.scalars(
            select(MailMessage)
            .options(defer(MailMessage.html_body), defer(MailMessage.body))
            .order_by(MailMessage.received_at.desc(), MailMessage.id.desc())
            .limit(limit)
        ).all()
    )
    members = [item for item in rows if _subject_key(item.subject, item.id, project_id) == key]
    if project_id:
        rules = [rule for rule in _rules(session, project_id) if rule.enabled]
        members = [item for item in members if _row_matches(rules, item, project_id)]
    if len(members) < 2:
        return [], 0
    show = get_int("mail", "threads.show_limit", project_id=scope)
    items = [
        {
            "id": item.id,
            "title": item.subject or _title(item, project_id),
            "from_name": item.from_name,
            "from_addr": item.from_addr,
            "received_at": item.received_at.isoformat(),
            "read": bool(item.read),
            "archived": bool(item.archived),
        }
        for item in members[:show]
    ]
    return items, len(members)


def _subject_key(subject: str, message_id: int, project_id: int | None) -> str:
    scope = project_id or None
    if not get_bool("mail", "threads.enabled", project_id=scope):
        return "id:" + str(message_id)
    prefixes = _thread_prefixes()
    passes = get_int("mail", "threads.strip_passes", project_id=scope)
    folded = _fold_subject(subject, prefixes, passes)
    if not folded:
        if get_bool("mail", "threads.group_empty", project_id=scope):
            return "empty"
        return "id:" + str(message_id)
    return folded


def _clean_subject(subject: str, project_id: int | None) -> str:
    prefixes = _thread_prefixes()
    passes = get_int("mail", "threads.strip_passes", project_id=project_id or None)
    text_value = " ".join((subject or "").split())
    for _ in range(max(1, passes)):
        updated = _strip_prefix(text_value, prefixes)
        if updated == text_value:
            break
        text_value = updated
    return text_value.strip(" -")


def _fold_subject(subject: str, prefixes: list[str], passes: int) -> str:
    text_value = " ".join((subject or "").split())
    for _ in range(max(1, passes)):
        updated = _strip_prefix(text_value, prefixes)
        if updated == text_value:
            break
        text_value = updated
    return text_value.strip(" -").casefold()


def _thread_prefixes() -> list[str]:
    raw = get("mail", "threads.prefixes")
    prefixes = []
    if isinstance(raw, list):
        for item in raw:
            text_value = str(item or "").strip().casefold()
            if text_value and text_value not in prefixes:
                prefixes.append(text_value)
    prefixes.sort(key=len, reverse=True)
    return prefixes


def _strip_prefix(text_value: str, prefixes: list[str]) -> str:
    folded = text_value.casefold()
    for prefix in prefixes:
        if not folded.startswith(prefix):
            continue
        rest = text_value[len(prefix):]
        match = re.match(r"\s*(?:\[\d+\]|\(\d+\))?\s*[:\-]\s*", rest)
        if match:
            return rest[match.end():].strip()
    return text_value
