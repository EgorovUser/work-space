from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.db import get_db
from app.core.deps import require_project, set_project_loader
from app.core.models import User
from app.core.settings_store import register_defs
from app.modules.projects import events, service
from app.modules.projects.models import Project
from app.modules.projects.settings import DEFS

router = APIRouter()


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None


class ArchiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archived: bool = True


@router.get("/api/home")
def home(db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    return service.home(db, user.id)


@router.get("/api/projects")
def list_projects(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return {"items": service.list_projects(db, user.id, include_archived)}


@router.post("/api/projects", status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_project(db, user.id, body.name, body.description)


@router.get("/api/projects/{project_id}")
def get_project(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.project_card(db, project, user.id)


@router.patch("/api/projects/{project_id}")
def patch_project(
    body: ProjectPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_project(db, project, user.id, body.model_dump(exclude_unset=True))


@router.post("/api/projects/{project_id}/archive")
def archive_project(
    body: ArchiveBody,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.set_archived(db, project, user.id, body.archived)


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str


@router.get("/api/projects/{project_id}/notes")
def list_notes(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": service.list_notes(db, project.id)}


@router.post("/api/projects/{project_id}/notes", status_code=201)
def create_note(
    body: NoteBody,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_note(db, project.id, user.id, body.body)


@router.patch("/api/projects/{project_id}/notes/{note_id}")
def patch_note(
    note_id: int,
    body: NoteBody,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_note(db, project.id, user.id, note_id, body.body)


@router.delete("/api/projects/{project_id}/notes/{note_id}", status_code=204)
def delete_note(
    note_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_note(db, project.id, user.id, note_id)


@router.get("/api/projects/{project_id}/dashboard")
def dashboard(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.project_dashboard(db, project, user.id)


@router.get("/api/projects/{project_id}/search")
def search(
    q: str = "",
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.project_search(db, project, user.id, q)


def setup(app) -> None:
    register_defs(DEFS)
    set_project_loader(service.load_project)
    events.register()
    app.include_router(router)
