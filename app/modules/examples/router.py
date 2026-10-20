from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.bridge import register_materialize, register_search
from app.core.counters import register_project_counters
from app.modules.examples.service import counters as counters_service
from app.core.db import get_db
from app.core.deps import require_project
from app.core.models import User
from app.core.settings_store import register_defs
from app.modules.examples import service
from app.modules.examples.settings import DEFS
from app.modules.projects.models import Project

router = APIRouter()


class ExampleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body: str = ""
    note: str = ""
    language: str | None = None
    pinned: bool = False
    tags: list[str] = []


class ExamplePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    body: str | None = None
    note: str | None = None
    language: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    tags: list[str] | None = None
    # Оптимистичная блокировка: если пример успели изменить в другой вкладке,
    # сервер ответит 409 вместо тихой перезаписи.
    updated_at: str | None = None


@router.get("/api/projects/{project_id}/examples")
def list_examples(
    include_archived: bool = False,
    language: str = "",
    q: str = "",
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_examples(db, project.id, include_archived, language, q)


@router.get("/api/projects/{project_id}/example-tags")
def list_tags(project: Project = Depends(require_project), db: Session = Depends(get_db)) -> dict:
    return service.list_tags(db, project.id)


@router.post("/api/projects/{project_id}/examples", status_code=201)
def create_example(
    body: ExampleIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_example(db, project.id, user.id, body.model_dump())


@router.post("/api/projects/{project_id}/examples/upload", status_code=201)
def upload_example(
    file: UploadFile = File(...),
    note: str = Form(""),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.import_file(db, project.id, user.id, file, note)


@router.get("/api/projects/{project_id}/examples/{example_id}")
def get_example(
    example_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.get_example(db, project.id, example_id)


@router.patch("/api/projects/{project_id}/examples/{example_id}")
def patch_example(
    example_id: int,
    body: ExamplePatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_example(db, project.id, user.id, example_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/examples/{example_id}", status_code=204)
def delete_example(
    example_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_example(db, project.id, user.id, example_id)


@router.post("/api/projects/{project_id}/examples/{example_id}/files", status_code=201)
def add_file(
    example_id: int,
    file: UploadFile = File(...),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.add_file(db, project.id, user.id, example_id, file)


@router.delete("/api/projects/{project_id}/examples/{example_id}/files/{link_id}", status_code=204)
def delete_file(
    example_id: int,
    link_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_file(db, project.id, user.id, example_id, link_id)


def _materialize_example(session, project_id: int, user_id: int, upload) -> dict:
    created = service.import_file(session, project_id, user_id, upload, "")
    first = (created.get("files") or [None])[0] or {}
    return {"target_id": created["id"], "title": created["title"], "file_id": first.get("file_id")}


def setup(app) -> None:
    register_defs(DEFS)
    register_project_counters("examples", counters_service.project_counts)
    register_materialize("example", _materialize_example)
    register_search("examples", service.search_provider)
    app.include_router(router)
