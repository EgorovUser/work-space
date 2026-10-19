from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import user_id_var
from app.core.db import get_db, session_scope
from app.core.logging import log_scope, logger
from app.core.models import User

router = APIRouter()
_dummy_hash: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("Пароль длиннее 72 байт")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except Exception:
        return False


def _dummy() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("dummy-password")
    return _dummy_hash


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    session_version = request.session.get("session_version")
    if not user_id:
        raise HTTPException(status_code=401, detail="Требуется вход")
    user = db.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or session_version is None
        or session_version != user.session_version
    ):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Требуется вход")
    user_id_var.set(str(user.id))
    return user


@router.post("/api/auth/login", response_model=UserOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> User:
    with log_scope("auth", "login"):
        user = db.scalars(select(User).where(User.username == body.username)).one_or_none()
        password_hash = user.password_hash if user is not None else _dummy()
        valid = verify_password(body.password, password_hash)
        if user is None or not user.is_active or not valid:
            logger.warning("login failed username={}", body.username)
            raise HTTPException(status_code=401, detail="Неверный логин или пароль")
        request.session["user_id"] = user.id
        request.session["session_version"] = user.session_version
        user_id_var.set(str(user.id))
        logger.info("login user_id={}", user.id)
        return user


@router.post("/api/auth/logout")
def logout(request: Request, user: User = Depends(require_user)) -> dict:
    with log_scope("auth", "logout", user_id=user.id):
        request.session.clear()
        logger.info("logout user_id={}", user.id)
    return {"ok": True}


@router.post("/api/auth/logout-all")
def logout_all(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)) -> dict:
    with log_scope("auth", "logout-all", user_id=user.id):
        user.session_version += 1
        db.add(user)
        db.commit()
        request.session.clear()
        logger.info("logout-all user_id={}", user.id)
    return {"ok": True}


@router.post("/api/auth/password")
def change_password(
    body: PasswordChangeIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    with log_scope("auth", "password", user_id=user.id):
        if not verify_password(body.old_password, user.password_hash):
            logger.warning("password change failed user_id={}", user.id)
            raise HTTPException(status_code=400, detail="Неверный текущий пароль")
        if body.new_password == body.old_password:
            raise HTTPException(status_code=400, detail="Новый пароль совпадает со старым")
        if len(body.new_password.encode("utf-8")) > 72:
            raise HTTPException(status_code=400, detail="Пароль длиннее 72 байт")
        if len(body.new_password) < 8:
            raise HTTPException(status_code=400, detail="Пароль короче 8 символов")
        user.password_hash = hash_password(body.new_password)
        user.session_version += 1
        db.add(user)
        db.commit()
        request.session.clear()
        logger.info("password changed user_id={}", user.id)
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    session_version = request.session.get("session_version")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or session_version is None
        or session_version != user.session_version
    ):
        request.session.clear()
        return None
    user_id_var.set(str(user.id))
    return UserOut.model_validate(user)


@router.get("/api/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_user)) -> list[User]:
    return list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id)).all())


def healthcheck() -> None:
    with session_scope() as session:
        session.scalar(select(func.count()).select_from(User))
