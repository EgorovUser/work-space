from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.bridge import on_project_created, register_card, register_dashboard, register_inbox, register_search
from app.core.db import get_db
from app.core.deps import require_project
from app.core.models import User
from app.core.scheduler import register_job
from app.core.settings_store import register_defs
from app.modules.projects.models import Project
from app.modules.tasks import events, service
from app.modules.tasks.settings import DEFS

router = APIRouter()


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    color: str = ""
    is_closed: bool = False


class StatusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    color: str | None = None
    is_closed: bool | None = None


class IdsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int]


class TaskOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_id: int
    ids: list[int]


class TaskReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orders: list[TaskOrder]


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    status_id: int | None = None
    assignee_id: int | None = None
    priority: str | None = None
    progress_mode: str | None = None
    progress_manual: int = 0
    deadline: str | None = None
    tag_ids: list[int] = []
    repeat_kind: str | None = None
    repeat_interval: int | None = None
    repeat_until: str | None = None


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    status_id: int | None = None
    assignee_id: int | None = None
    priority: str | None = None
    progress_mode: str | None = None
    progress_manual: int | None = None
    deadline: str | None = None
    tag_ids: list[int] | None = None
    repeat_kind: str | None = None
    repeat_interval: int | None = None
    repeat_until: str | None = None


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str


class CheckPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    done: bool | None = None


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str


class TagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


@router.get("/api/tasks/search")
def picker_search(
    q: str = "",
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    """Открытые задачи всех проектов по запросу — выбор задачи для помодоро.

    Живой FTS5-поиск с префиксными словами (регистр не важен): закрытые,
    удалённые в корзину и задачи архивных проектов в выдачу не попадают.
    """
    return {"items": service.search_tasks(db, q, service.clamp_limit(limit))}


@router.get("/api/projects/{project_id}/task-statuses")
def list_statuses(project: Project = Depends(require_project), db: Session = Depends(get_db)) -> dict:
    return {"items": service.list_statuses(db, project.id)}


@router.post("/api/projects/{project_id}/task-statuses", status_code=201)
def create_status(
    body: StatusIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_status(db, project.id, user.id, body.name, body.color, body.is_closed)


@router.patch("/api/projects/{project_id}/task-statuses/{status_id}")
def patch_status(
    status_id: int,
    body: StatusPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_status(db, project.id, user.id, status_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/task-statuses/{status_id}", status_code=204)
def delete_status(
    status_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_status(db, project.id, user.id, status_id)


@router.post("/api/projects/{project_id}/task-statuses/order")
def order_statuses(
    body: IdsBody,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return {"items": service.order_statuses(db, project.id, user.id, body.ids)}


@router.get("/api/projects/{project_id}/tags")
def list_tags(project: Project = Depends(require_project), db: Session = Depends(get_db)) -> dict:
    return {"items": service.list_tags(db, project.id)}


@router.post("/api/projects/{project_id}/tags", status_code=201)
def create_tag(
    body: TagIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_tag(db, project.id, user.id, body.name)


@router.delete("/api/projects/{project_id}/tags/{tag_id}", status_code=204)
def delete_tag(
    tag_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_tag(db, project.id, user.id, tag_id)


@router.get("/api/projects/{project_id}/tasks")
def list_tasks(project: Project = Depends(require_project), db: Session = Depends(get_db)) -> dict:
    return service.list_tasks(db, project.id)


@router.post("/api/projects/{project_id}/tasks", status_code=201)
def create_task(
    body: TaskIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_task(db, project.id, user.id, body.model_dump())


@router.post("/api/projects/{project_id}/tasks/reorder")
def reorder_tasks(
    body: TaskReorder,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    for order in body.orders:
        service.order_tasks(db, project.id, user.id, order.status_id, order.ids)
    return {"ok": True}


@router.post("/api/projects/{project_id}/tasks/order")
def order_tasks(
    body: TaskOrder,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    service.order_tasks(db, project.id, user.id, body.status_id, body.ids)
    return {"ok": True}


@router.get("/api/projects/{project_id}/tasks/{task_id}")
def get_task(
    task_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    return service.get_task(db, project.id, task_id)


@router.patch("/api/projects/{project_id}/tasks/{task_id}")
def patch_task(
    task_id: int,
    body: TaskPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_task(db, project.id, user.id, task_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_task(db, project.id, user.id, task_id)


@router.post("/api/projects/{project_id}/tasks/{task_id}/checklist", status_code=201)
def add_check(
    task_id: int,
    body: CheckIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.add_check(db, project.id, user.id, task_id, body.title)


@router.patch("/api/projects/{project_id}/tasks/{task_id}/checklist/{item_id}")
def patch_check(
    task_id: int,
    item_id: int,
    body: CheckPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_check(db, project.id, user.id, task_id, item_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/tasks/{task_id}/checklist/{item_id}", status_code=204)
def delete_check(
    task_id: int,
    item_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_check(db, project.id, user.id, task_id, item_id)


@router.post("/api/projects/{project_id}/tasks/{task_id}/checklist/order")
def order_checks(
    task_id: int,
    body: IdsBody,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
) -> dict:
    service.order_checks(db, project.id, task_id, body.ids)
    return {"ok": True}


@router.post("/api/projects/{project_id}/tasks/{task_id}/comments", status_code=201)
def add_comment(
    task_id: int,
    body: CommentIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.add_comment(db, project.id, user.id, task_id, body.body)


@router.post("/api/projects/{project_id}/tasks/{task_id}/files", status_code=201)
def add_file(
    task_id: int,
    file: UploadFile = File(...),
    kind: str = Form(...),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.add_attachment(db, project.id, user.id, task_id, file, kind)


@router.delete("/api/projects/{project_id}/tasks/{task_id}/files/{link_id}", status_code=204)
def delete_file(
    task_id: int,
    link_id: int,
    kind: str = "",
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_attachment(db, project.id, user.id, task_id, link_id, kind)


def setup(app) -> None:
    register_defs(DEFS)
    events.register()
    service.backfill_statuses()
    on_project_created(service.seed_project)
    register_card("tasks", service.card_provider)
    register_inbox("tasks", service.inbox_provider)
    register_dashboard("tasks", service.dashboard_provider)
    register_search("tasks", service.search_provider)
    register_job(
        "tasks.deadlines",
        service.check_deadlines,
        module="tasks",
        action="deadlines",
        interval_module="tasks",
        interval_key="deadlines.interval_seconds",
        label="Сроки задач",
        detail="Просроченные задачи и близкий срок",
    )
    app.include_router(router)
