from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import require_user
from app.core.db import get_db
from app.core.models import User
from app.core.settings_store import register_defs
from app.modules.ui import catalog, service
from app.modules.ui.settings import DEFS

router = APIRouter()


class UiConfigPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, object]]
    # Настройки страницы (максимум высоты блоков и будущее) — обязательны:
    # клиент всегда шлёт полный конфиг, «частичный» PUT молча сбрасывал бы
    # настройки тем, кто прислал только элементы.
    settings: dict[str, object]


def _require_page(page_name: str) -> None:
    if catalog.get_page(page_name) is None:
        raise HTTPException(status_code=404, detail="Неизвестная страница")


@router.get("/api/ui/{page}")
def get_ui_page(
    page: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    _require_page(page)
    return service.page_state(db, user.id, page)


@router.put("/api/ui/{page}")
def put_ui_page(
    page: str,
    body: UiConfigPut,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    _require_page(page)
    return service.save_config(db, user.id, page, body.items, body.settings, user.id)


@router.post("/api/ui/{page}/reset")
def reset_ui_page(
    page: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    _require_page(page)
    return service.reset_config(db, user.id, page, user.id)


@router.get("/api/ui/{page}/revisions")
def list_ui_revisions(
    page: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    _require_page(page)
    return service.list_revisions(db, user.id, page)


@router.post("/api/ui/{page}/revisions/{revision_id}/restore")
def restore_ui_revision(
    page: str,
    revision_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    _require_page(page)
    try:
        return service.restore_revision(db, user.id, page, revision_id, user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def setup(app) -> None:
    register_defs(DEFS)
    app.include_router(router)
