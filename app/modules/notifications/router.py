from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.db import get_db
from app.core.events_catalog import ALL_EVENTS
from app.core.models import User
from app.core.outbox import subscribe
from app.core.bridge import register_home_block
from app.core.scheduler import register_job
from app.core.settings_store import register_defs
from app.modules.notifications import service
from app.modules.notifications.settings import DEFS

router = APIRouter()


@router.get("/api/notifications/meta")
def meta(user: User = Depends(require_user)) -> dict:
    return service.meta(user.id)


@router.get("/api/notifications/unread")
def unread(db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    return service.unread(db, user.id)


@router.get("/api/notifications")
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.list_notifications(db, user.id, unread_only)


@router.post("/api/notifications/test/{channel}")
def test_channel(channel: str, user: User = Depends(require_user)) -> dict:
    return service.probe(user.id, channel)


@router.post("/api/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    return service.mark_all_read(db, user.id)


@router.post("/api/notifications/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    return service.mark_read(db, user.id, notification_id)


def setup(app) -> None:
    register_defs(DEFS)
    for event_type in ALL_EVENTS:
        subscribe(event_type, service.handle)
    register_home_block("notifications", service.home_items)
    register_job(
        "notifications.deliver",
        service.deliver_due,
        module="notifications",
        action="deliver",
        interval_module="notifications",
        interval_key="job.seconds",
        label="Доставка уведомлений",
        detail="Повтор неудачных отправок и догон каналов, которые включили позже",
        enabled_module="notifications",
        enabled_key="job.enabled",
    )
    app.include_router(router)
