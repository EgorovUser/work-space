"""Забор писем по IMAP. Пароль в лог не пишется, его сюда передают уже открытым."""

from __future__ import annotations

import imaplib


def check_login(host: str, port: int, use_ssl: bool, username: str, password: str, folder: str, timeout: int) -> str | None:
    client = None
    try:
        client = _open(host, port, use_ssl, timeout)
        client.login(username, password)
        typ, _ = client.select(folder, readonly=True)
        if typ != "OK":
            return "Не открыли папку"
        return None
    except Exception as exc:
        return _safe(exc, password)
    finally:
        _close(client)


def pull(
    host: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    folder: str,
    last_uid: int,
    limit: int,
    timeout: int,
) -> tuple[list[tuple[int, bytes]], str | None]:
    client = None
    try:
        client = _open(host, port, use_ssl, timeout)
        client.login(username, password)
        typ, _ = client.select(folder, readonly=True)
        if typ != "OK":
            return [], "Не открыли папку"
        uids = _uids(client, last_uid, limit)
        messages: list[tuple[int, bytes]] = []
        for uid in uids:
            raw = _fetch(client, uid)
            if raw:
                messages.append((uid, raw))
        return messages, None
    except Exception as exc:
        return [], _safe(exc, password)
    finally:
        _close(client)


def pull_recent(
    host: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    folder: str,
    since: str,
    skip: set[int],
    limit: int,
    timeout: int,
) -> tuple[list[tuple[int, bytes]], str | None]:
    client = None
    try:
        client = _open(host, port, use_ssl, timeout)
        client.login(username, password)
        typ, _ = client.select(folder, readonly=True)
        if typ != "OK":
            return [], "Не открыли папку"
        typ, data = client.uid("SEARCH", "SINCE", since)
        if typ != "OK":
            return [], "Не нашли письма за окно"
        numbers = [item for item in sorted(_numbers(data)) if item not in skip]
        if len(numbers) > limit:
            numbers = numbers[-limit:]
        messages: list[tuple[int, bytes]] = []
        for uid in numbers:
            raw = _fetch(client, uid)
            if raw:
                messages.append((uid, raw))
        return messages, None
    except Exception as exc:
        return [], _safe(exc, password)
    finally:
        _close(client)


def pull_uid(
    host: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    folder: str,
    uid: int,
    timeout: int,
) -> tuple[bytes | None, str | None]:
    client = None
    try:
        client = _open(host, port, use_ssl, timeout)
        client.login(username, password)
        typ, _ = client.select(folder, readonly=True)
        if typ != "OK":
            return None, "Не открыли папку"
        return _fetch(client, uid), None
    except Exception as exc:
        return None, _safe(exc, password)
    finally:
        _close(client)


def pull_older(
    host: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    folder: str,
    before_uid: int,
    limit: int,
    timeout: int,
) -> tuple[list[tuple[int, bytes]], str | None]:
    client = None
    try:
        client = _open(host, port, use_ssl, timeout)
        client.login(username, password)
        typ, _ = client.select(folder, readonly=True)
        if typ != "OK":
            return [], "Не открыли папку"
        uids = _older(client, before_uid, limit)
        messages: list[tuple[int, bytes]] = []
        for uid in uids:
            raw = _fetch(client, uid)
            if raw:
                messages.append((uid, raw))
        return messages, None
    except Exception as exc:
        return [], _safe(exc, password)
    finally:
        _close(client)


def copy_message(
    host: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    source: str,
    uid: int,
    target: str,
    move: bool,
    timeout: int,
    message_id: str = "",
) -> tuple[str | None, int | None]:
    """Возвращает ошибку и новый uid, если письмо ушло из исходной папки. None значит uid прежний."""
    client = None
    try:
        client = _open(host, port, use_ssl, timeout)
        client.login(username, password)
        typ, _ = client.select(source, readonly=False)
        if typ != "OK":
            return "Не открыли папку", None
        encoded = _utf7(target)
        created = client.create(encoded)
        if created[0] not in ("OK", "NO"):
            return "Папку проекта не создали", None
        if move:
            moved = client.uid("MOVE", str(uid), encoded)
            if moved[0] == "OK":
                return None, _uid_after_move(client, encoded, message_id)
            copied = client.uid("COPY", str(uid), encoded)
            if copied[0] != "OK":
                return "Сервер не перенёс и не скопировал письмо", None
            return None, None
        copied = client.uid("COPY", str(uid), encoded)
        if copied[0] != "OK":
            return "Письмо не скопировали", None
        return None, None
    except Exception as exc:
        return _safe(exc, password), None
    finally:
        _close(client)


def _uid_after_move(client, folder: str, message_id: str) -> int:
    found = _uid_by_header(client, folder, message_id)
    return found if found else 0


def _uid_by_header(client, folder: str, message_id: str) -> int | None:
    token = (message_id or "").strip().replace('"', "")
    if not token:
        return None
    typ, _ = client.select(folder, readonly=True)
    if typ != "OK":
        return None
    typ, data = client.uid("SEARCH", "HEADER", "Message-ID", '"' + token + '"')
    if typ != "OK":
        return None
    numbers = _numbers(data)
    if not numbers:
        return None
    return numbers[-1]


def _older(client, before_uid: int, limit: int) -> list[int]:
    if before_uid <= 1:
        return []
    typ, data = client.uid("SEARCH", "UID", "1:" + str(before_uid - 1))
    if typ != "OK":
        raise imaplib.IMAP4.error("поиск старых писем не удался")
    numbers = sorted(_numbers(data))
    if len(numbers) > limit:
        return numbers[-limit:]
    return numbers


def _utf7(name: str) -> str:
    import base64

    result: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        raw = "".join(buf).encode("utf-16-be")
        token = base64.b64encode(raw).decode("ascii").rstrip("=").replace("/", ",")
        result.append("&" + token + "-")
        buf.clear()

    for char in name.replace("/", " ").replace("\n", " ").strip() or "Проект":
        code = ord(char)
        if 32 <= code <= 126 and char != "&":
            flush()
            result.append(char)
        elif char == "&":
            flush()
            result.append("&-")
        else:
            buf.append(char)
    flush()
    return "".join(result)


def _open(host: str, port: int, use_ssl: bool, timeout: int):
    if use_ssl:
        return imaplib.IMAP4_SSL(host, port, timeout=timeout)
    return imaplib.IMAP4(host, port, timeout=timeout)


def _uids(client, last_uid: int, limit: int) -> list[int]:
    if last_uid:
        typ, data = client.uid("SEARCH", "UID", str(last_uid + 1) + ":*")
    else:
        typ, data = client.uid("SEARCH", "ALL")
    if typ != "OK":
        raise imaplib.IMAP4.error("поиск писем не удался")
    numbers = sorted(item for item in _numbers(data) if item > last_uid)
    if not last_uid and len(numbers) > limit:
        return numbers[-limit:]
    return numbers[:limit]


def _numbers(data) -> list[int]:
    blob = data[0] if data else b""
    if isinstance(blob, bytes):
        return [int(item) for item in blob.split() if item.isdigit()]
    return []


def _fetch(client, uid: int) -> bytes | None:
    typ, data = client.uid("FETCH", str(uid), "(RFC822)")
    if typ != "OK" or not data:
        return None
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return None


def _close(client) -> None:
    if client is None:
        return
    try:
        client.logout()
    except Exception:
        try:
            client.shutdown()
        except Exception:
            pass


def _safe(exc: Exception, password: str) -> str:
    text = " ".join(str(exc).split()) or exc.__class__.__name__
    if password:
        text = text.replace(password, "***")
    return text
