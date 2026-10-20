from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.bridge import register_card, register_dashboard, register_inbox, register_search
from app.core.db import get_db
from app.core.deps import require_project
from app.core.models import User
from app.core.scheduler import register_job
from app.core.settings_store import get_int, register_defs
from app.modules.mail import service
from app.modules.mail.settings import DEFS
from app.modules.projects.models import Project

router = APIRouter()


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    port: int | None = None
    use_ssl: bool | None = None
    username: str = ""
    password: str = ""
    folder: str = ""
    enabled: bool | None = None


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    host: str | None = None
    port: int | None = None
    use_ssl: bool | None = None
    username: str | None = None
    password: str | None = None
    folder: str | None = None
    enabled: bool | None = None


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    field: str
    op: str
    value: str
    action: str
    enabled: bool | None = None


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    field: str | None = None
    op: str | None = None
    value: str | None = None
    action: str | None = None
    enabled: bool | None = None


class MessagePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: bool | None = None
    archived: bool | None = None


class FolderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int | None = None
    move: bool = False


class DocumentTarget(BaseModel):
    """Куда положить документ из вложения (общий ящик)."""

    model_config = ConfigDict(extra="forbid")

    project_id: int


class TagRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    op: str
    value: str


class TagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    color: str
    rules: list[TagRuleIn] = []


class TagAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_id: int
    on: bool


class NotifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    match: str
    gate_filed: bool


class NotifyRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    op: str
    value: str


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


def setup(app) -> None:
    service.ensure_schema()
    register_defs(DEFS)
    register_card("mail", service.card_provider)
    register_inbox("mail", service.inbox_provider)
    register_inbox("events", service.events_today)
    register_dashboard("mail", service.dashboard_provider)
    register_search("mail", service.search_provider)
    register_job(
        "mail.poll",
        service.poll_accounts,
        module="mail",
        action="poll",
        interval_module="mail",
        interval_key="job.seconds",
        label="Забор почты",
        detail="Новые и ещё не скачанные письма",
        enabled_module="mail",
        enabled_key="job.enabled",
    )
    register_job(
        "mail.events",
        service.remind_events,
        module="mail",
        action="events",
        interval_module="mail",
        interval_key="events.check_seconds",
        label="События из почты",
        detail="Напоминания «сегодня» и «скоро»",
        enabled_module="mail",
        enabled_key="events.remind",
    )
    app.include_router(router)
