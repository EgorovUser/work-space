from __future__ import annotations

import re
import sys
from contextlib import contextmanager

from loguru import logger

from app.core.context import action_var, module_var, request_id_var, user_id_var

_SECRET_VALUE = re.compile(
    r"(?i)((?:password|passwd|secret|token|authorization|api_key|fernet|smtp_password|cookie)"
    r"[\"']?\s*[:=]\s*[\"']?)(\S+)"
)
_BEARER = re.compile(r"(?i)(bearer\s+)(\S+)")
_FERNET = re.compile(r"gAAAAA[A-Za-z0-9_\-=]+")

_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {extra[module]} | {extra[action]} | "
    "req={extra[request_id]} | user={extra[user_id]} | {message}"
)


def mask(text: str) -> str:
    text = _BEARER.sub(r"\1***", text)
    text = _SECRET_VALUE.sub(r"\1***", text)
    text = _FERNET.sub("***", text)
    return text


def _patch(record: dict) -> None:
    record["extra"]["module"] = module_var.get()
    record["extra"]["action"] = action_var.get()
    record["extra"]["request_id"] = request_id_var.get()
    record["extra"]["user_id"] = user_id_var.get()
    record["message"] = mask(str(record["message"]))


def bootstrap() -> None:
    logger.remove()
    logger.configure(
        patcher=_patch,
        extra={"module": "app", "action": "-", "request_id": "-", "user_id": "-"},
    )
    level = "DEBUG"
    try:
        from app.core.config import get as get_config

        level = get_config().log_level
    except Exception:
        level = "DEBUG"
    logger.add(sys.stderr, level=level, format=_FORMAT, backtrace=True, diagnose=False)


def apply_settings() -> None:
    from app.core.config import get as get_config
    from app.core.settings_store import get_int

    cfg = get_config()
    rotation = str(get_int("core", "logs.rotation_mb")) + " MB"
    retention = str(get_int("core", "logs.retention_days")) + " days"
    log_dir = cfg.data_path() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=cfg.log_level, format=_FORMAT, backtrace=True, diagnose=False)
    logger.add(
        log_dir / "app.log",
        level=cfg.log_level,
        format=_FORMAT,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )
    logger.add(
        log_dir / "errors.log",
        level="WARNING",
        format=_FORMAT,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )


@contextmanager
def log_scope(module: str, action: str, user_id: str | int | None = None):
    token_module = module_var.set(module)
    token_action = action_var.set(action)
    token_user = user_id_var.set(str(user_id)) if user_id is not None else None
    try:
        yield
    finally:
        if token_user is not None:
            user_id_var.reset(token_user)
        action_var.reset(token_action)
        module_var.reset(token_module)
