"""Разбор VEVENT из текста календаря. Сетевых вызовов здесь нет."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def parse_ics(text: str, zone_name: str, limit: int) -> list[dict]:
    if not text or "VEVENT" not in text.upper():
        return []
    try:
        zone = ZoneInfo(zone_name or "UTC")
    except Exception:
        zone = timezone.utc
    unfolded = text.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")
    found = []
    for chunk in unfolded.split("BEGIN:VEVENT")[1:]:
        body = chunk.split("END:VEVENT", 1)[0]
        item = _event(body, zone)
        if item is not None:
            found.append(item)
        if len(found) >= limit:
            break
    return found


def _event(body: str, zone) -> dict | None:
    fields: dict[str, str] = {}
    for line in body.split("\n"):
        if ":" not in line:
            continue
        left, value = line.split(":", 1)
        name = left.split(";", 1)[0].strip().upper()
        if name and name not in fields:
            fields[name] = value.strip()
    start = _when(fields.get("DTSTART") or "", zone)
    if start is None:
        return None
    summary = fields.get("SUMMARY") or "Событие"
    return {
        "uid": (fields.get("UID") or summary)[:200],
        "summary": summary[:300],
        "starts_at": start,
        "ends_at": _when(fields.get("DTEND") or "", zone),
        "location": (fields.get("LOCATION") or "")[:300],
    }


def _when(value: str, zone) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z") and "T" in raw:
            parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        elif "T" in raw:
            parsed = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone)
        else:
            parsed = datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=zone)
    except Exception:
        return None
    return parsed.astimezone(timezone.utc)
