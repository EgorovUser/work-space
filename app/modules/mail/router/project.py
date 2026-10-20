"""Почта проекта /api/projects/{id}/mail*: ящики, правила, импорт, письма."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.db import get_db
from app.core.deps import require_project
from app.core.models import User
from app.core.settings_store import get_int
from app.modules.mail import service
from app.modules.mail.router.schemas import AccountIn, AccountPatch, FolderBody, MessagePatch, RuleIn, RulePatch
from app.modules.projects.models import Project

router = APIRouter()


@router.get("/api/projects/{project_id}/mail")
def project_mail(
    unread: bool = False,
    include_archived: bool = False,
    q: str = "",
    offset: int = 0,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.project_mail(db, project.id, unread, include_archived, q, offset)


@router.post("/api/projects/{project_id}/mail/accounts", status_code=201)
def create_account(
    body: AccountIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_account(db, project.id, user.id, body.model_dump())


@router.patch("/api/projects/{project_id}/mail/accounts/{account_id}")
def update_account(
    account_id: int,
    body: AccountPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_account(db, project.id, user.id, account_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/mail/accounts/{account_id}", status_code=204)
def delete_account(
    account_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_account(db, project.id, user.id, account_id)


@router.post("/api/projects/{project_id}/mail/accounts/{account_id}/check")
def check_account(
    account_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.check_account(db, project.id, user.id, account_id)


@router.post("/api/projects/{project_id}/mail/accounts/{account_id}/fetch")
def fetch_account(
    account_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.fetch_account(db, project.id, user.id, account_id)


@router.post("/api/projects/{project_id}/mail/rules", status_code=201)
def create_rule(
    body: RuleIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_rule(db, project.id, user.id, body.model_dump())


@router.patch("/api/projects/{project_id}/mail/rules/{rule_id}")
def update_rule(
    rule_id: int,
    body: RulePatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_rule(db, project.id, user.id, rule_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/mail/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_rule(db, project.id, user.id, rule_id)


@router.post("/api/projects/{project_id}/mail/import", status_code=201)
def import_message(
    file: UploadFile = File(...),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    raw = file.file.read(get_int("mail", "message.max_bytes") + 1)
    return service.import_raw(db, project.id, user.id, raw)


@router.post("/api/projects/{project_id}/mail/messages/{message_id}/attachments/{section}")
def download_attachment(
    message_id: int,
    section: str,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.download_attachment(db, project.id, user.id, message_id, section)


@router.post("/api/projects/{project_id}/mail/messages/{message_id}/attachments/{section}/document", status_code=201)
def attachment_to_document(
    message_id: int,
    section: str,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    # Документ ложится в проект ящика (или в выбранный — через поле).
    return service.attachment_to_document(db, project.id, user.id, message_id, section)


@router.post("/api/projects/{project_id}/mail/messages/{message_id}/folder")
def folder_message(
    message_id: int,
    body: FolderBody,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.place_message(db, user.id, message_id, project.name, body.move)


@router.get("/api/projects/{project_id}/mail/messages/{message_id}")
def get_message(
    message_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.get_message(db, project.id, user.id, message_id)


@router.patch("/api/projects/{project_id}/mail/messages/{message_id}")
def update_message(
    message_id: int,
    body: MessagePatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_message(db, project.id, user.id, message_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/mail/messages/{message_id}", status_code=204)
def delete_message(
    message_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_message(db, project.id, user.id, message_id)
