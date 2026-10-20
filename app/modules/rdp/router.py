from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.bridge import register_search
from app.core.db import get_db
from app.core.deps import require_project
from app.core.models import User
from app.core.settings_store import register_defs
from app.modules.projects.models import Project
from app.modules.rdp import service
from app.modules.rdp.settings import DEFS

router = APIRouter()


class RdpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    port: int | None = None
    username: str = ""
    domain: str = ""
    note: str = ""


class RdpPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    domain: str | None = None
    note: str | None = None
    archived: bool | None = None
    # Оптимистичная блокировка: при несовпадении сервер ответит 409.
    updated_at: str | None = None


@router.get("/api/projects/{project_id}/rdp")
def list_connections(
    include_archived: bool = False,
    q: str = "",
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_connections(db, project.id, include_archived, q)


@router.post("/api/projects/{project_id}/rdp", status_code=201)
def create_connection(
    body: RdpIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_connection(db, project.id, user.id, body.model_dump())


@router.get("/api/projects/{project_id}/rdp/{rdp_id}")
def get_connection(
    rdp_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.get_connection(db, project.id, rdp_id)


@router.get("/api/projects/{project_id}/rdp/{rdp_id}/file")
def download_connection_file(
    rdp_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> Response:
    data = service.connection_file(db, project.id, user.id, rdp_id)
    return Response(
        content=data["content"],
        media_type="application/x-rdp",
        headers={
            "Content-Disposition": 'attachment; filename="' + data["filename"] + '"',
            # Файл строится из текущей записи — кешировать нельзя.
            "Cache-Control": "no-store",
        },
    )


@router.patch("/api/projects/{project_id}/rdp/{rdp_id}")
def patch_connection(
    rdp_id: int,
    body: RdpPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_connection(db, project.id, user.id, rdp_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/rdp/{rdp_id}", status_code=204)
def delete_connection(
    rdp_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_connection(db, project.id, user.id, rdp_id)


def setup(app) -> None:
    register_defs(DEFS)
    register_search("rdp", service.search_provider)
    app.include_router(router)
