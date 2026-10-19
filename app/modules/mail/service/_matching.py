"""Примитивы сопоставления письма с правилами.

Общие для правил проектов, хештегов и уведомлений,
поэтому лежат отдельным нижним слоем.
"""

from __future__ import annotations

from app.core.settings_store import get_bool
from app.modules.mail.models import MailMessage, MailRule


def _row_matches(rules: list[MailRule], row: MailMessage, project_id: int) -> bool:
    if not rules:
        return False
    parsed = {
        "from_name": row.from_name or "",
        "from_addr": row.from_addr or "",
        "to_addr": row.to_addr or "",
        "subject": row.subject or "",
        "body": row.body or "",
    }
    casefold = get_bool("mail", "rules.casefold", project_id=project_id)
    return any(_matches(rule, parsed, casefold) for rule in rules)


def _matches(rule, parsed: dict, casefold: bool) -> bool:
    hay = _haystack(rule.field, parsed)
    needle = rule.value or ""
    if casefold:
        hay = hay.casefold()
        needle = needle.casefold()
    if rule.op == "equals":
        return hay.strip() == needle.strip()
    if rule.op == "not_contains":
        return needle not in hay
    return needle in hay


def _haystack(field: str, parsed: dict) -> str:
    if field == "from":
        return (parsed.get("from_name") or "") + " " + (parsed.get("from_addr") or "")
    if field == "to":
        return parsed.get("to_addr") or ""
    if field == "subject":
        return parsed.get("subject") or ""
    return parsed.get("body") or ""
