from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.bridge import register_card, register_dashboard
from app.core.db import get_db
from app.core.deps import require_project
from app.core.models import User
from app.core.scheduler import register_job
from app.core.settings_store import register_defs
from app.modules.projects.models import Project
from app.modules.timetracking import overview as overview_service
from app.modules.timetracking import service
from app.modules.timetracking.settings import DEFS

router = APIRouter()


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = ""
    task_id: int | None = None


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = ""
    task_id: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    minutes: int | None = None
    day: str | None = None


class EntryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = None
    task_id: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    minutes: int | None = None


@router.get("/api/time/overview")
def time_overview(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    """Сводка по всем проектам сразу (патч S): текущая и прошлая недели."""
    return overview_service.overview(db)


@router.get("/api/projects/{project_id}/time")
def project_time(
    days: int | None = None,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.project_time(db, project.id, user.id, days)


@router.post("/api/projects/{project_id}/time/start", status_code=201)
def start_timer(
    body: StartIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.start_timer(db, project.id, user.id, body.model_dump())


@router.post("/api/projects/{project_id}/time/stop")
def stop_timer(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.stop_timer(db, project.id, user.id)


@router.post("/api/projects/{project_id}/time/entries", status_code=201)
def create_entry(
    body: EntryIn,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.create_entry(db, project.id, user.id, body.model_dump())


@router.patch("/api/projects/{project_id}/time/entries/{entry_id}")
def update_entry(
    entry_id: int,
    body: EntryPatch,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.update_entry(db, project.id, user.id, entry_id, body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}/time/entries/{entry_id}", status_code=204)
def delete_entry(
    entry_id: int,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> None:
    service.delete_entry(db, project.id, user.id, entry_id)


def setup(app) -> None:
    register_defs(DEFS)
    register_card("timetracking", service.card_provider)
    register_dashboard("timetracking", service.dashboard_provider)
    register_job(
        "timetracking.autostop",
        service.autostop_open,
        module="timetracking",
        action="autostop",
        interval_module="timetracking",
        interval_key="timer.job_seconds",
        label="Автостоп таймера",
        detail="Останавливает таймер, который идёт слишком долго",
    )
    app.include_router(router)
