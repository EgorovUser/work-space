"""Содержимое задачи: чеклист, комментарии, вложения (документы и примеры)."""

from __future__ import annotations

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.bridge import materialize
from app.core.db import utcnow
from app.core.events_catalog import (
    TASK_CHECKLIST_ADDED,
    TASK_CHECKLIST_DONE,
    TASK_COMMENT,
    TASK_FILE,
)
from app.core.logging import log_scope, logger
from app.core.models import FileLink
from app.core.outbox import enqueue
from app.core.settings_store import get_int
from app.modules.projects.service import touch_project
from app.modules.tasks import events
from app.modules.tasks.models import ChecklistItem, TaskRef
from app.modules.tasks.service._queries import _check, _checks, _task
from app.modules.tasks.service._serialize import _check_out, _ref_out, _task_full
from app.modules.tasks.service._validators import _clean


def add_check(session: Session, project_id: int, user_id: int, task_id: int, title: str) -> dict:
    task = _task(session, project_id, task_id)
    count = session.scalar(select(func.count()).select_from(ChecklistItem).where(ChecklistItem.task_id == task.id)) or 0
    if count >= get_int("tasks", "checklist.max_items"):
        raise HTTPException(status_code=400, detail="Слишком много пунктов")
    row = ChecklistItem(
        task_id=task.id,
        title=_clean(title, "checklist.title.max_length", "Укажите пункт"),
        done=False,
        position=count,
    )
    session.add(row)
    events.add_event(session, task.id, user_id, events.CHECKLIST)
    task.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        TASK_CHECKLIST_ADDED,
        {
            "title": row.title,
            "subject": task.title,
            "project_id": project_id,
            "task_id": task.id,
            "link": "/projects/" + str(project_id) + "/tasks/" + str(task.id),
        },
        user_id=user_id,
    )
    with log_scope("tasks", "checklist", user_id=user_id):
        logger.info("checklist added id={} task={}", row.id, task.id)
    return _check_out(row)


def update_check(session: Session, project_id: int, user_id: int, task_id: int, item_id: int, fields: dict) -> dict:
    task = _task(session, project_id, task_id)
    row = _check(session, task.id, item_id)
    if "title" in fields and fields["title"] is not None:
        row.title = _clean(fields["title"], "checklist.title.max_length", "Укажите пункт")
    if "done" in fields and fields["done"] is not None:
        row.done = bool(fields["done"])
        if row.done:
            enqueue(
                session,
                TASK_CHECKLIST_DONE,
                {"title": row.title, "subject": task.title, "project_id": project_id, "task_id": task.id, "link": "/projects/" + str(project_id) + "/tasks/" + str(task.id)},
                user_id=user_id,
            )
    events.add_event(session, task.id, user_id, events.CHECKLIST)
    task.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    with log_scope("tasks", "checklist", user_id=user_id):
        logger.info("checklist updated id={} task={} done={}", row.id, task.id, row.done)
    return _check_out(row)


def delete_check(session: Session, project_id: int, user_id: int, task_id: int, item_id: int) -> None:
    task = _task(session, project_id, task_id)
    row = _check(session, task.id, item_id)
    session.delete(row)
    task.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    with log_scope("tasks", "checklist.delete", user_id=user_id):
        logger.info("checklist deleted id={} task={}", item_id, task.id)


def order_checks(session: Session, project_id: int, task_id: int, ids: list[int]) -> None:
    task = _task(session, project_id, task_id)
    rows = {row.id: row for row in _checks(session, task.id)}
    if set(ids) != set(rows):
        raise HTTPException(status_code=400, detail="Передайте все пункты")
    for position, item_id in enumerate(ids):
        rows[item_id].position = position
    session.flush()
    with log_scope("tasks", "checklist.order"):
        logger.info("checklist ordered task={} count={}", task.id, len(ids))


def add_comment(session: Session, project_id: int, user_id: int, task_id: int, body: str) -> dict:
    task = _task(session, project_id, task_id)
    text = _clean(body, "comment.max_length", "Пустой комментарий")
    events.add_event(session, task.id, user_id, events.COMMENT, text)
    task.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        TASK_COMMENT,
        {"title": "Комментарий", "subject": task.title, "project_id": project_id, "task_id": task.id, "link": "/projects/" + str(project_id) + "/tasks/" + str(task.id)},
        user_id=user_id,
    )
    with log_scope("tasks", "comment", user_id=user_id):
        logger.info("comment task={}", task.id)
    return _task_full(session, task)


def add_attachment(session: Session, project_id: int, user_id: int, task_id: int, upload: UploadFile, kind: str) -> dict:
    task = _task(session, project_id, task_id)
    chosen = (kind or "").strip()
    if chosen not in ("document", "example"):
        raise HTTPException(status_code=400, detail="Выберите документ или пример")
    try:
        made = materialize(chosen, session, project_id, user_id, upload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ref = TaskRef(
        task_id=task.id,
        project_id=project_id,
        kind=chosen,
        target_id=int(made["target_id"]),
        title=made.get("title") or upload.filename or "файл",
        file_id=made.get("file_id"),
        created_at=utcnow(),
    )
    session.add(ref)
    events.add_event(session, task.id, user_id, events.ATTACHMENT, ref.title)
    task.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    with log_scope("tasks", "attach", user_id=user_id):
        logger.info("attachment task={} kind={} target={}", task.id, chosen, ref.target_id)
    enqueue(
        session,
        TASK_FILE,
        {"title": ref.title, "subject": task.title, "project_id": project_id, "task_id": task.id, "link": "/projects/" + str(project_id) + "/tasks/" + str(task.id)},
        user_id=user_id,
    )
    return _ref_out(ref)


def delete_attachment(session: Session, project_id: int, user_id: int, task_id: int, link_id: int, kind: str = "") -> None:
    task = _task(session, project_id, task_id)
    chosen = (kind or "").strip()
    if chosen in ("document", "example"):
        ref = session.get(TaskRef, link_id)
        if ref is None or ref.task_id != task.id or ref.project_id != project_id:
            raise HTTPException(status_code=404, detail="Ссылка не найдена")
        session.delete(ref)
        task.updated_at = utcnow()
        session.flush()
        with log_scope("tasks", "attach.delete", user_id=user_id):
            logger.info("task link deleted task={} kind={} target={}", task.id, ref.kind, ref.target_id)
        return
    link = session.get(FileLink, link_id)
    if link is None or link.module != "tasks" or link.entity_type != "task" or link.entity_id != task.id:
        raise HTTPException(status_code=404, detail="Вложение не найдено")
    if link.project_id not in (None, project_id):
        raise HTTPException(status_code=404, detail="Вложение не найдено")
    session.delete(link)
    task.updated_at = utcnow()
    session.flush()
    with log_scope("tasks", "attach.delete", user_id=user_id):
        logger.info("attachment deleted task={} link={}", task.id, link_id)
