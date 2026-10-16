"""Отправка в Telegram и по SMTP. Токен и пароль в текст ошибки не попадают."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import requests

from app.core.settings_store import get_bool, get_int, get_str
from app.modules.notifications.token import normalize_bot_token, token_problem


def check_telegram(user_id: int) -> tuple[str, str]:
    token, problem = _bot(user_id)
    chat = get_str("notifications", "telegram.chat_id", user_id=user_id).strip()
    if problem:
        return "bad", problem
    if not chat:
        return "warn", "Не задан чат"
    base = _api(user_id) + "/bot" + token
    timeout = get_int("core", "http.outbound_timeout_seconds")
    try:
        me = requests.get(base + "/getMe", timeout=timeout)
        me_data = _json(me)
        if me.status_code >= 400 or not me_data.get("ok"):
            return "bad", _telegram_error(str(me_data.get("description") or ""), token)
        chat_response = requests.post(base + "/getChat", json={"chat_id": chat}, timeout=timeout)
        chat_data = _json(chat_response)
        if chat_response.status_code >= 400 or not chat_data.get("ok"):
            return "bad", _telegram_error(str(chat_data.get("description") or ""), token)
        return "ok", "Бот отвечает, чат доступен"
    except Exception as exc:
        return "bad", _mask(str(exc), token)


def check_email(user_id: int) -> tuple[str, str]:
    host = get_str("notifications", "smtp.host", user_id=user_id).strip()
    to_addr = get_str("notifications", "smtp.to", user_id=user_id).strip()
    from_addr = get_str("notifications", "smtp.from", user_id=user_id).strip()
    if not host or not to_addr or not from_addr:
        return "warn", "Не задан сервер, отправитель или получатель"
    port = get_int("notifications", "smtp.port", user_id=user_id)
    username = get_str("notifications", "smtp.username", user_id=user_id).strip()
    password = get_str("notifications", "smtp.password", user_id=user_id)
    use_ssl = get_bool("notifications", "smtp.ssl", user_id=user_id)
    starttls = get_bool("notifications", "smtp.starttls", user_id=user_id)
    timeout = get_int("core", "http.outbound_timeout_seconds")
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as client:
                _login(client, username, password)
                client.noop()
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as client:
                if starttls:
                    client.starttls()
                _login(client, username, password)
                client.noop()
        return "ok", "Сервер принял вход, письмо не отправлялось"
    except Exception as exc:
        return "bad", _mask(str(exc), password)


def _json(response) -> dict:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def send_telegram(user_id: int, text: str) -> tuple[str, str]:
    token, problem = _bot(user_id)
    chat = get_str("notifications", "telegram.chat_id", user_id=user_id).strip()
    if problem:
        return "failed", problem
    if not chat:
        return "skipped", "Не задан чат"
    url = _api(user_id) + "/bot" + token + "/sendMessage"
    timeout = get_int("core", "http.outbound_timeout_seconds")
    try:
        response = requests.post(url, json={"chat_id": chat, "text": text}, timeout=timeout)
        data = _json(response)
        if response.status_code >= 400 or not data.get("ok"):
            return "failed", _telegram_error(str(data.get("description") or ""), token)
        return "sent", ""
    except Exception as exc:
        return "failed", _mask(str(exc), token)


def _bot(user_id: int) -> tuple[str, str]:
    raw = get_str("notifications", "telegram.bot_token", user_id=user_id)
    problem = token_problem(raw)
    if problem:
        return "", problem
    return normalize_bot_token(raw), ""


def _api(user_id: int) -> str:
    return get_str("notifications", "telegram.api_url", user_id=user_id).rstrip("/") or "https://api.telegram.org"


def _telegram_error(detail: str, token: str) -> str:
    text = _mask(detail, token).strip()
    folded = text.casefold()
    if folded in ("not found", "unauthorized") or folded.endswith("not found") and "chat" not in folded:
        return token_problem(token) or "Telegram не принял токен и ответил Not Found. Вставьте токен из BotFather целиком."
    if "chat not found" in folded or "chat_id is empty" in folded:
        return "Чат не найден. Сначала напишите боту любое сообщение и проверьте числовой id."
    if "bot was blocked" in folded:
        return "Бот заблокирован в этом чате."
    if "forbidden" in folded:
        return "Боту нельзя писать в этот чат. " + text
    return text or "Telegram не принял сообщение"


def send_email(user_id: int, subject: str, text: str) -> tuple[str, str]:
    host = get_str("notifications", "smtp.host", user_id=user_id).strip()
    to_addr = get_str("notifications", "smtp.to", user_id=user_id).strip()
    from_addr = get_str("notifications", "smtp.from", user_id=user_id).strip()
    if not host or not to_addr or not from_addr:
        return "skipped", "Не задан сервер, отправитель или получатель"
    port = get_int("notifications", "smtp.port", user_id=user_id)
    username = get_str("notifications", "smtp.username", user_id=user_id).strip()
    password = get_str("notifications", "smtp.password", user_id=user_id)
    use_ssl = get_bool("notifications", "smtp.ssl", user_id=user_id)
    starttls = get_bool("notifications", "smtp.starttls", user_id=user_id)
    timeout = get_int("core", "http.outbound_timeout_seconds")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = to_addr
    message.set_content(text)
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as client:
                _login(client, username, password)
                client.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as client:
                if starttls:
                    client.starttls()
                _login(client, username, password)
                client.send_message(message)
        return "sent", ""
    except Exception as exc:
        return "failed", _mask(str(exc), password)


def _login(client, username: str, password: str) -> None:
    if username:
        client.login(username, password)


def _mask(text: str, secret: str) -> str:
    cleaned = " ".join((text or "").split())
    if secret:
        cleaned = cleaned.replace(secret, "***")
    return cleaned
