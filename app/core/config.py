from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    secret_key: str = ""
    fernet_key: str = ""
    fernet_key_old: str = ""
    data_dir: str = ""
    database_url: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    seed_username: str = "admin"
    seed_password: str = ""

    def data_path(self) -> Path:
        if self.data_dir:
            path = Path(self.data_dir)
            if not path.is_absolute():
                path = ROOT / path
            return path
        return ROOT / "data"

    def sqlite_url(self) -> str:
        if self.database_url:
            return self.database_url
        return "sqlite:///" + (self.data_path() / "app.db").as_posix()


_config: AppConfig | None = None


def get() -> AppConfig:
    if _config is None:
        raise RuntimeError("Конфиг ещё не подготовлен")
    return _config


def prepare() -> AppConfig:
    global _config
    cfg = AppConfig()
    data = cfg.data_path()
    data.mkdir(parents=True, exist_ok=True)
    (data / "files").mkdir(parents=True, exist_ok=True)
    (data / "logs").mkdir(parents=True, exist_ok=True)
    _fill_secrets(cfg, data)
    Fernet(cfg.fernet_key.encode("ascii"))
    if cfg.fernet_key_old:
        Fernet(cfg.fernet_key_old.encode("ascii"))
    _config = cfg
    return cfg


def _fill_secrets(cfg: AppConfig, data: Path) -> None:
    boot = data / "bootstrap.env"
    stored: dict[str, str] = {}
    if boot.exists():
        for line in boot.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            stored[key.strip()] = value.strip()

    if not cfg.secret_key:
        cfg.secret_key = stored.get("SECRET_KEY", "")
    if not cfg.fernet_key:
        cfg.fernet_key = stored.get("FERNET_KEY", "")

    if cfg.app_env == "prod" and (not cfg.secret_key or not cfg.fernet_key):
        raise RuntimeError("В APP_ENV=prod нужны SECRET_KEY и FERNET_KEY")

    generated = False
    if not cfg.secret_key:
        cfg.secret_key = secrets.token_urlsafe(32)
        generated = True
    if not cfg.fernet_key:
        cfg.fernet_key = Fernet.generate_key().decode("ascii")
        generated = True
    if generated:
        boot.write_text(
            "SECRET_KEY=" + cfg.secret_key + "\nFERNET_KEY=" + cfg.fernet_key + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(boot, 0o600)
        except OSError:
            pass
