"""Каналы доставки уведомлений: реестр + отправка в Telegram и по SMTP.

Реестр (патч AQ) — единая точка расширения: новый канал = ChannelDef и
один вызов register_channel, каталог/матрица/доставка/пробы подхватывают
его сами. Клиентские каналы (browser, os) тоже живут здесь — без отправки:
они доставляются вкладкой (лента/бейдж и системный тост). Токен и пароль
в текст ошибки не попадают.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable

import requests

from app.core.settings_store import get_bool, get_int, get_str
from app.modules.notifications.token import normalize_bot_token, token_problem


@dataclass(frozen=True)
class ChannelDef:
    """Канал доставки: как он называется и кто за него отвечает.

    - server_delivery=False — канал живёт у клиента (лента, системный
      тост): строк NotificationDelivery он не создаёт, сервер его не
      ретраит и не догоняет;
    - sender — серверная отправка (user_id, subject, text) → (status, error);
    - tester — кнопка «Проверить»: (user_id) → (status, error).
    """

    id: str
    label: str
    default_enabled: bool = False
    server_delivery: bool = True
    sender: Callable[[int, str, str], tuple[str, str]] | None = None
    tester: Callable[[int], tuple[str, str]] | None = None


_registry: dict[str, ChannelDef] = {}


def register_channel(item: ChannelDef) -> None:
    """Зарегистрировать канал (повторная регистрация того же id — замена)."""
    _registry[item.id] = item


def channel_def(channel: str) -> ChannelDef | None:
    return _registry.get(channel)


def all_channels() -> list[ChannelDef]:
    return list(_registry.values())


def catalog() -> list[dict]:
    """Каталог для настройки channels и матрицы: id + label по порядку регистрации."""
    return [{"id": item.id, "label": item.label} for item in _registry.values()]


def default_flags() -> dict[str, bool]:
    """Дефолтные каналы для события: браузер включён, остальное — осознанно."""
    return {item.id: item.default_enabled for item in _registry.values()}


def is_server_channel(channel: str) -> bool:
    """Создаёт ли канал серверные строки доставок (ретраи, догон)."""
    item = _registry.get(channel)
    return bool(item and item.server_delivery)


def send(channel: str, user_id: int, subject: str, text: str) -> tuple[str, str]:
    item = _registry.get(channel)
    if item is None or item.sender is None or not item.server_delivery:
        return "skipped", "Неизвестный канал"
    return item.sender(user_id, subject, text)


def test_channel(channel: str, user_id: int) -> tuple[str, str]:
    """Кнопка «Проверить»: реальная отправка пробного сообщения."""
    item = _registry.get(channel)
    if item is None or item.tester is None or not item.server_delivery:
        return "skipped", "Неизвестный канал"
    return item.tester(user_id)


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


def send_telegram(user_id: int, subject: str, text: str) -> tuple[str, str]:
    """Отправка в Telegram по контракту реестра: sender(user_id, subject, text).

    У сообщения Telegram нет темы, а исходящий текст `_outgoing` уже
    начинается с заголовка уведомления — subject сознательно не
    используется (префикс дублировал бы первую строку).
    """
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


# --- регистрации: порядок здесь = порядок в каталоге и матрице ----------
# (в конце файла: регистрации ссылаются на отправку, описанную выше)

register_channel(ChannelDef(id="browser", label="В приложении", default_enabled=True, server_delivery=False))
register_channel(ChannelDef(id="os", label="Системные уведомления", server_delivery=False))
register_channel(
    ChannelDef(
        id="telegram",
        label="Telegram",
        sender=send_telegram,
        tester=lambda user_id: send_telegram(
            user_id, "Проверка канала", "Проверка: бот доставляет сообщения из рабочего пространства."
        ),
    )
)
register_channel(
    ChannelDef(
        id="email",
        label="Почта",
        sender=send_email,
        tester=lambda user_id: send_email(
            user_id, "Проверка почты", "Проверка: письмо из рабочего пространства дошло."
        ),
    )
)
