"""Общий ящик /api/mail*: письма, метки, правила уведомлений, ящики без проекта."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.db import get_db
from app.core.models import User
from app.modules.mail import service
from app.modules.mail.router.schemas import (
    AccountIn,
    AccountPatch,
    DocumentTarget,
    FolderBody,
    MessagePatch,
    NotifyIn,
    NotifyRuleIn,
    TagAssign,
    TagIn,
)
from app.modules.projects.models import Project

router = APIRouter()


@router.get("/api/mail")
def mailbox(
    unread: bool = False,
    include_archived: bool = False,
    q: str = "",
    tag: int = 0,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.mailbox(db, unread, include_archived, q, tag, offset)


@router.get("/api/mail/tags")
def list_tags(db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    return service.tag_page(db)


@router.post("/api/mail/tags", status_code=201)
def create_tag(
    body: TagIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_tag(db, user.id, body.model_dump())


@router.delete("/api/mail/tags/{tag_id}", status_code=204)
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_tag(db, user.id, tag_id)


@router.put("/api/mail/notify")
def save_notify(
    body: NotifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.save_notify(db, user.id, body.model_dump())


@router.post("/api/mail/notify/rules", status_code=201)
def create_notify_rule(
    body: NotifyRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_notify_rule(db, user.id, body.model_dump())


@router.delete("/api/mail/notify/rules/{rule_id}")
def delete_notify_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.delete_notify_rule(db, user.id, rule_id)


@router.post("/api/mail/messages/{message_id}/tags")
def assign_tag(
    message_id: int,
    body: TagAssign,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.set_message_tag(db, user.id, message_id, body.tag_id, body.on)


@router.post("/api/mail/accounts", status_code=201)
def create_global_account(
    body: AccountIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_account(db, 0, user.id, body.model_dump())


@router.patch("/api/mail/accounts/{account_id}")
def update_global_account(
    account_id: int,
    body: AccountPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    row = service._account_any(db, account_id)
    return service.update_account(db, row.project_id, user.id, account_id, body.model_dump(exclude_unset=True))


@router.delete("/api/mail/accounts/{account_id}", status_code=204)
def delete_global_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    row = service._account_any(db, account_id)
    service.delete_account(db, row.project_id, user.id, account_id)


@router.post("/api/mail/accounts/{account_id}/test")
def test_global_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.test_account(db, user.id, account_id)


@router.post("/api/mail/accounts/{account_id}/fetch")
def fetch_global_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    row = service._account_any(db, account_id)
    return service.fetch_account(db, row.project_id, user.id, account_id)


@router.get("/api/mail/messages/{message_id}")
def global_message(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.get_message(db, 0, user.id, message_id)


@router.patch("/api/mail/messages/{message_id}")
def update_global_message(
    message_id: int,
    body: MessagePatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_message(db, 0, user.id, message_id, body.model_dump(exclude_unset=True))


@router.delete("/api/mail/messages/{message_id}", status_code=204)
def delete_global_message(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_message(db, 0, user.id, message_id)


@router.post("/api/mail/messages/{message_id}/attachments/{section}")
def download_global_attachment(
    message_id: int,
    section: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.download_attachment(db, 0, user.id, message_id, section)


@router.post("/api/mail/messages/{message_id}/attachments/{section}/document", status_code=201)
def attachment_to_document_global(
    message_id: int,
    section: str,
    body: DocumentTarget,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    # Из общего ящика проект для документа выбирает пользователь.
    return service.attachment_to_document(db, 0, user.id, message_id, section, body.project_id)


@router.post("/api/mail/messages/{message_id}/folder")
def folder_global_message(
    message_id: int,
    body: FolderBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    project = db.get(Project, body.project_id or 0)
    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return service.place_message(db, user.id, message_id, project.name, body.move)
