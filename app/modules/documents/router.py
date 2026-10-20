from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.bridge import register_dashboard, register_materialize, register_search
from app.core.counters import register_project_counters
from app.modules.documents.service import counters as counters_service
from app.core.db import get_db
from app.core.deps import require_project
from app.core.models import User
from app.core.scheduler import register_job
from app.core.settings_store import register_defs
from app.modules.documents import events, service
from app.modules.documents.settings import DEFS
from app.modules.projects.models import Project

router = APIRouter()


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    note: str | None = None
    archived: bool | None = None
    # Оптимистичная блокировка: если запись успели изменить в другой вкладке,
    # сервер ответит 409 вместо тихой перезаписи.
    updated_at: str | None = None


@router.get("/api/projects/{project_id}/documents")
def list_documents(
    include_archived: bool = False,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_documents(db, project.id, include_archived)


@router.post("/api/projects/{project_id}/documents", status_code=201)
def create_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    note: str = Form(""),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_document(db, project.id, user.id, file, title, note)


@router.get("/api/projects/{project_id}/documents/{document_id}")
def get_document(
    document_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.get_document(db, project.id, document_id)


@router.patch("/api/projects/{project_id}/documents/{document_id}")
def patch_document(
    document_id: int,
    body: DocumentPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_document(db, project.id, user.id, document_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/documents/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_document(db, project.id, user.id, document_id)


@router.get("/api/projects/{project_id}/documents/{document_id}/text")
def document_text(
    document_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.document_text(db, project.id, document_id)


@router.post("/api/projects/{project_id}/documents/{document_id}/versions", status_code=201)
def add_version(
    document_id: int,
    file: UploadFile = File(...),
    note: str = Form(""),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.add_version(db, project.id, user.id, document_id, file, note)


@router.delete("/api/projects/{project_id}/documents/{document_id}/versions/{version_id}", status_code=204)
def delete_version(
    document_id: int,
    version_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_version(db, project.id, user.id, document_id, version_id)


def _materialize_document(session, project_id: int, user_id: int, upload) -> dict:
    created = service.create_document(session, project_id, user_id, upload, "", "")
    current = created.get("current") or {}
    return {"target_id": created["id"], "title": created["title"], "file_id": current.get("file_id")}


def setup(app) -> None:
    service.ensure_parsers()
    register_defs(DEFS)
    events.register()
    register_project_counters("documents", counters_service.project_counts)
    register_materialize("document", _materialize_document)
    register_dashboard("documents", service.dashboard_provider)
    register_search("documents", service.search_provider)
    register_job(
        "documents.extract",
        service.retry_extract,
        module="documents",
        action="extract",
        interval_module="documents",
        interval_key="extract.retry_seconds",
        label="Разбор документов",
        detail="Повторный разбор файлов, которые не разобрались",
    )
    app.include_router(router)
