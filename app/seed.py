from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.auth import hash_password, verify_password
from app.core.config import get as get_config
from app.core.db import session_scope
from app.core.logging import log_scope, logger
from app.core.models import User

_DEV_PASSWORD = "admin"


def seed() -> None:
    cfg = get_config()
    with session_scope() as session:
        users = list(session.scalars(select(User)).all())
        if not users:
            password = cfg.seed_password
            used_default = False
            if not password:
                if cfg.app_env == "prod":
                    raise RuntimeError("SEED_PASSWORD нужен, чтобы создать первого пользователя")
                password = _DEV_PASSWORD
                used_default = True
            user = User(
                username=cfg.seed_username,
                password_hash=hash_password(password),
                display_name=cfg.seed_username,
                is_active=True,
            )
            session.add(user)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return
            with log_scope("auth", "seed", user_id=user.id):
                logger.info("seed user created username={}", user.username)
                if used_default:
                    logger.warning("seed user uses the dev password, change it")
            return

        if cfg.app_env == "prod" and len(users) == 1:
            user = users[0]
            if user.username == "admin" and verify_password(_DEV_PASSWORD, user.password_hash):
                logger.warning(
                    "production user 'admin' still has the default password 'admin'; change it"
                )
