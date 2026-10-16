from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.db import get_db, session_scope
from app.core.models import User
from app.core.registry import ModuleDisabled, is_enabled

_project_loader = None


def set_project_loader(loader) -> None:
    global _project_loader
    _project_loader = loader


def ensure_project(project_id: int) -> None:
    if _project_loader is None or not is_enabled("projects"):
        raise ModuleDisabled("projects")
    with session_scope() as session:
        if _project_loader(session, project_id) is None:
            raise HTTPException(status_code=404, detail="Проект не найден")


def require_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not is_enabled("projects") or _project_loader is None:
        raise ModuleDisabled("projects")
    project = _project_loader(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return project
