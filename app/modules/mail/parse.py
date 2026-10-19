"""Разбор письма из байтов RFC822. Сеть здесь не используется."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime, parseaddr

from app.core.db import utcnow
from app.modules.mail import ics


_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def parse_message(raw: bytes, limits: dict) -> dict:
    if not raw:
        raise ValueError("пустое письмо")
    if len(raw) > int(limits["max_bytes"]):
        raise ValueError("письмо слишком большое")
    msg = message_from_bytes(raw)
    subject = _clip(_header(msg, "Subject"), limits["subject"])
    from_name, from_addr = parseaddr(_header(msg, "From"))
    to_name, to_addr = parseaddr(_header(msg, "To"))
    if not to_addr and to_name:
        to_addr = to_name
    body, html_body, attachments, events = _parts(msg, limits)
    return {
        "rfc_message_id": _clip(_header(msg, "Message-ID").strip("<> "), limits["address"]),
        "from_name": _clip(from_name, limits["address"]),
        "from_addr": _clip(from_addr, limits["address"]),
        "to_addr": _clip(to_addr, limits["address"]),
        "subject": subject,
        "body": body,
        "html": html_body,
        "received_at": _date(msg),
        "attachments": attachments,
        "events": events,
    }


def _parts(msg, limits: dict) -> tuple[str, str, list[dict], list[dict]]:
    plain: list[str] = []
    html_parts: list[str] = []
    files: list[dict] = []
    events: list[dict] = []
    parts = list(msg.walk() if msg.is_multipart() else [msg])
    section = 0
    for part in parts:
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True) or b""
        disposition = (part.get_content_disposition() or "").lower()
        filename = _filename(part)
        current = str(section)
        section += 1
        ctype = part.get_content_type()
        if ctype == "text/calendar" or filename.lower().endswith(".ics"):
            text = _decode(payload, part.get_content_charset(), limits["encodings"])
            events.extend(ics.parse_ics(text, limits.get("zone") or "UTC", int(limits.get("events") or 20)))
            if filename:
                files.append({"filename": filename, "mime": ctype or "text/calendar", "size": len(payload), "section": current})
            continue
        if disposition == "attachment" or (filename and ctype not in ("text/plain", "text/html")):
            if filename:
                files.append(
                    {
                        "filename": filename,
                        "mime": ctype or "application/octet-stream",
                        "size": len(payload),
                        "section": current,
                    }
                )
            continue
        text = _decode(payload, part.get_content_charset(), limits["encodings"])
        if ctype == "text/html":
            html_parts.append(text)
        else:
            plain.append(text)
    body = "\n".join(item.strip() for item in plain if item.strip())
    html_body = _sanitize("\n".join(html_parts))
    if not body:
        body = _html_text(html_body)
    return _clip(body.strip(), limits["body"]), _clip(html_body, limits["html"]), files, events


def part_bytes(raw: bytes, section: str, limits: dict) -> tuple[str, str, bytes]:
    parsed_msg = message_from_bytes(raw)
    parts = list(parsed_msg.walk() if parsed_msg.is_multipart() else [parsed_msg])
    index = 0
    for part in parts:
        if part.is_multipart():
            continue
        current = str(index)
        index += 1
        if current != str(section):
            continue
        payload = part.get_payload(decode=True) or b""
        if len(payload) > int(limits["max_bytes"]):
            raise ValueError("вложение слишком большое")
        filename = _filename(part) or "файл"
        return filename, part.get_content_type() or "application/octet-stream", payload
    raise ValueError("вложение не найдено")


def _filename(part) -> str:
    raw = part.get_filename()
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _header(msg, name: str) -> str:
    raw = msg.get(name)
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _decode(payload: bytes, charset: str | None, encodings: list) -> str:
    tried = []
    if charset:
        tried.append(charset)
    for item in encodings:
        if item and item not in tried:
            tried.append(item)
    for encoding in tried:
        try:
            return payload.decode(encoding)
        except Exception:
            continue
    return payload.decode("utf-8", errors="replace")


def _sanitize(value: str) -> str:
    text = re.sub(r"(?is)<(script|iframe|object|embed|form|link|base|meta)\b[^>]*>.*?</\1>", " ", value or "")
    text = re.sub(r"(?is)<(script|iframe|object|embed|form|link|base|meta)\b[^>]*?/?>", " ", text)
    text = re.sub(r"(?i)\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", " ", text)
    text = re.sub(r"(?i)(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", " ", text)
    text = re.sub(r"(?i)(href|src)\s*=\s*javascript:[^\s>]+", " ", text)
    return text.strip()


def _html_text(value: str) -> str:
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", value)
    text = re.sub(r"(?i)</\s*p\s*>", "\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return _SPACE.sub(" ", text).strip()


def _date(msg) -> datetime:
    for name in ("Date", "Resent-Date"):
        found = _parse_date(msg.get(name))
        if found is not None:
            return found
    for line in msg.get_all("Received") or []:
        if ";" not in line:
            continue
        found = _parse_date(line.rsplit(";", 1)[-1])
        if found is not None:
            return found
    return utcnow()


def _parse_date(raw) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except Exception:
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clip(value: str, limit: int) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return text[:limit]
