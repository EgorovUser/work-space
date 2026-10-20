from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.bridge import register_search
from app.core.db import get_db
from app.core.deps import require_project
from app.core.models import User
from app.core.settings_store import register_defs
from app.modules.projects.models import Project
from app.modules.secrets import service
from app.modules.secrets.settings import DEFS

router = APIRouter()


class SecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    username: str = ""
    url: str = ""
    note: str = ""
    secret: str = ""
    kind: str | None = None


class SecretPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    username: str | None = None
    url: str | None = None
    note: str | None = None
    secret: str | None = None
    kind: str | None = None
    archived: bool | None = None
    # Оптимистичная блокировка: если секрет успели изменить в другой вкладке,
    # сервер ответит 409 вместо тихой перезаписи.
    updated_at: str | None = None


@router.get("/api/projects/{project_id}/secrets")
def list_secrets(
    include_archived: bool = False,
    q: str = "",
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_secrets(db, project.id, include_archived, q)


@router.get("/api/secrets")
def list_all_secrets(
    include_archived: bool = False,
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    # Общий список секретов всех проектов — глобальный раздел «Секреты».
    # Значения не расшифровываются: только маскированные признаки, как и в
    # проектном списке; копирование идёт через существующие эндпоинты.
    return service.list_all_secrets(db, include_archived, q)


@router.post("/api/projects/{project_id}/secrets/generate")
def generate_secret(project: Project = Depends(require_project)) -> dict:
    return service.generate_secret(project.id)


@router.post("/api/projects/{project_id}/secrets", status_code=201)
def create_secret(
    body: SecretIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_secret(db, project.id, user.id, body.model_dump())


@router.get("/api/projects/{project_id}/secrets/{secret_id}")
def get_secret(
    secret_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.get_secret(db, project.id, secret_id)


@router.patch("/api/projects/{project_id}/secrets/{secret_id}")
def patch_secret(
    secret_id: int,
    body: SecretPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_secret(db, project.id, user.id, secret_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/secrets/{secret_id}", status_code=204)
def delete_secret(
    secret_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_secret(db, project.id, user.id, secret_id)


@router.post("/api/projects/{project_id}/secrets/{secret_id}/reveal")
def reveal_secret(
    secret_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.reveal_secret(db, project.id, user.id, secret_id)


@router.get("/api/projects/{project_id}/secrets/{secret_id}/revisions")
def list_revisions(
    secret_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    # История значений: метаданные снимков без расшифровки — что менялось
    # и когда. Копирование и откат идут отдельными эндпоинтами ниже.
    return service.list_revisions(db, project.id, secret_id)


@router.post("/api/projects/{project_id}/secrets/{secret_id}/revisions/{revision_id}/reveal")
def reveal_revision(
    secret_id: int,
    revision_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.reveal_revision(db, project.id, user.id, secret_id, revision_id)


@router.post("/api/projects/{project_id}/secrets/{secret_id}/revisions/{revision_id}/restore")
def restore_revision(
    secret_id: int,
    revision_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.restore_revision(db, project.id, user.id, secret_id, revision_id)


def setup(app) -> None:
    register_defs(DEFS)
    register_search("secrets", service.search_provider)
    app.include_router(router)
