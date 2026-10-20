"""Задачи доски: список, карточка, создание, изменение, удаление, порядок.

``list_tasks`` грузит чеклисты и метки батчами (``_checks_by_tasks`` +
``_tags_by_task``): доска любого размера обходится тремя запросами
вместо 1 + 2 на каждую задачу.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_catalog import (
    TASK_ASSIGNED,
    TASK_CREATED,
    TASK_DEADLINE_CHANGED,
    TASK_DELETED,
    TASK_STATUS_CHANGED,
    TASK_UPDATED,
)
from app.core.logging import log_scope, logger
from app.core.models import FileLink
from app.core.outbox import enqueue
from app.core.settings_store import get_int
from app.modules.projects.service import touch_project
from app.modules.tasks import events
from app.modules.tasks.models import ChecklistItem, Tag, Task, TaskEvent, TaskTag
from app.modules.tasks.service import recurrence
from app.modules.tasks.service._queries import (
    _checks_by_tasks,
    _next_position,
    _pick_status,
    _status,
    _tags_by_task,
    _task,
)
from app.modules.tasks.service._serialize import _event_payload, _task_brief_from, _task_full
from app.modules.tasks.service._validators import (
    _assignee,
    _clean,
    _deadline,
    _manual,
    _priority,
    _progress_mode,
    _repeat_interval,
    _repeat_kind,
    _repeat_until,
    _text,
)


def load_task(session: Session, task_id: int) -> Task | None:
    return session.get(Task, task_id)


def list_tasks(session: Session, project_id: int) -> dict:
    limit = get_int("tasks", "board.max_tasks", project_id=project_id)
    rows = session.scalars(
        select(Task).where(
            Task.project_id == project_id,
            # Задачи из корзины на доске не показываем (патч N).
            Task.deleted_at.is_(None),
        ).order_by(Task.position.asc(), Task.id.asc()).limit(limit)
    ).all()
    task_ids = [row.id for row in rows]
    checks_by_task = _checks_by_tasks(session, task_ids)
    tags_by_task = _tags_by_task(session, task_ids)
    items = []
    for row in rows:
        checks = checks_by_task.get(row.id, [])
        tags = tags_by_task.get(row.id, [])
        items.append(_task_brief_from(row, checks, tags))
    return {"items": items, "truncated": len(rows) >= limit}


def get_task(session: Session, project_id: int, task_id: int) -> dict:
    return _task_full(session, _task(session, project_id, task_id))


def create_task(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    status = _pick_status(session, project_id, fields.get("status_id"))
    priority = _priority(fields.get("priority"), project_id)
    mode = _progress_mode(fields.get("progress_mode"), project_id)
    manual = _manual(fields.get("progress_manual") or 0)
    assignee = _assignee(session, fields.get("assignee_id"))
    position = _next_position(session, status.id)
    kind = _repeat_kind(fields.get("repeat_kind"))
    interval = _repeat_interval(fields.get("repeat_interval")) if kind else 1
    until = _repeat_until(fields.get("repeat_until")) if kind else None
    task = Task(
        project_id=project_id,
        status_id=status.id,
        title=_clean(fields.get("title") or "", "title.max_length", "Укажите название"),
        description=_text(fields.get("description") or "", "description.max_length"),
        assignee_id=assignee,
        priority=priority,
        progress_mode=mode,
        progress_manual=manual,
        deadline=_deadline(fields.get("deadline")),
        repeat_kind=kind,
        repeat_interval=interval,
        repeat_until=until,
        position=position,
        created_by=user_id,
        closed_at=utcnow() if status.is_closed else None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(task)
    session.flush()
    _set_tags(session, project_id, task.id, fields.get("tag_ids") or [])
    events.add_event(session, task.id, user_id, events.CREATED)
    enqueue(session, TASK_CREATED, _event_payload(task), user_id=user_id)
    if assignee is not None:
        events.add_event(session, task.id, user_id, events.ASSIGNED)
        enqueue(session, TASK_ASSIGNED, _event_payload(task), user_id=user_id)
    touch_project(session, project_id)
    session.flush()
    with log_scope("tasks", "create", user_id=user_id):
        logger.info("task created id={} project={}", task.id, project_id)
    return _task_full(session, task)


def update_task(session: Session, project_id: int, user_id: int, task_id: int, fields: dict) -> dict:
    task = _task(session, project_id, task_id)
    notes: list[str] = []
    if "title" in fields and fields["title"] is not None:
        title = _clean(fields["title"], "title.max_length", "Укажите название")
        if title != task.title:
            task.title = title
            notes.append("название")
            events.add_event(session, task.id, user_id, events.UPDATED, "title")
    if "description" in fields and fields["description"] is not None:
        description = _text(fields["description"], "description.max_length")
        if description != task.description:
            task.description = description
            notes.append("описание")
            events.add_event(session, task.id, user_id, events.UPDATED, "description")
    if "priority" in fields and fields["priority"] is not None:
        priority = _priority(fields["priority"], project_id)
        if priority != task.priority:
            task.priority = priority
            notes.append("приоритет")
    if "progress_mode" in fields and fields["progress_mode"] is not None:
        mode = _progress_mode(fields["progress_mode"], project_id)
        if mode != task.progress_mode:
            task.progress_mode = mode
            notes.append("прогресс")
    if "progress_manual" in fields and fields["progress_manual"] is not None:
        manual = _manual(fields["progress_manual"])
        if manual != task.progress_manual:
            task.progress_manual = manual
            notes.append("прогресс")
    deadline_changed = False
    if "deadline" in fields:
        deadline = _deadline(fields["deadline"])
        if deadline != task.deadline:
            task.deadline = deadline
            deadline_changed = True
            events.add_event(session, task.id, user_id, events.DEADLINE)
    # Правило повтора разбираем до блока колонки: закрытие той же правкой
    # должно видеть уже обновлённое правило.
    if "repeat_kind" in fields and fields["repeat_kind"] is not None:
        kind = _repeat_kind(fields["repeat_kind"])
        if kind != task.repeat_kind:
            task.repeat_kind = kind
            notes.append("повтор")
        if not kind:
            task.repeat_interval = 1
            task.repeat_until = None
    if "repeat_interval" in fields and fields["repeat_interval"] is not None and task.repeat_kind:
        interval = _repeat_interval(fields["repeat_interval"])
        if interval != task.repeat_interval:
            task.repeat_interval = interval
            notes.append("повтор")
    if "repeat_until" in fields and task.repeat_kind:
        until = _repeat_until(fields["repeat_until"])
        if until != task.repeat_until:
            task.repeat_until = until
            notes.append("повтор")
    if "status_id" in fields and fields["status_id"] is not None and fields["status_id"] != task.status_id:
        status = _status(session, project_id, fields["status_id"])
        task.status_id = status.id
        task.position = _next_position(session, status.id)
        task.closed_at = utcnow() if status.is_closed else None
        events.add_event(session, task.id, user_id, events.STATUS, status.name)
        enqueue(session, TASK_STATUS_CHANGED, _event_payload(task, status_id=status.id), user_id=user_id)
        if status.is_closed:
            recurrence.spawn_next(session, project_id, user_id, task)
    if "assignee_id" in fields and fields["assignee_id"] != task.assignee_id:
        task.assignee_id = _assignee(session, fields["assignee_id"])
        events.add_event(session, task.id, user_id, events.ASSIGNED)
        payload = _event_payload(task)
        if task.assignee_id is None:
            payload["title"] = "Исполнителя сняли"
            payload["subject"] = task.title
        enqueue(session, TASK_ASSIGNED, payload, user_id=user_id)
    if "tag_ids" in fields and fields["tag_ids"] is not None:
        current = {link.tag_id for link in session.scalars(select(TaskTag).where(TaskTag.task_id == task.id)).all()}
        wanted = []
        for tag_id in fields["tag_ids"]:
            tag = session.get(Tag, tag_id)
            if tag is None or tag.project_id != project_id:
                raise HTTPException(status_code=400, detail="Метка не найдена")
            if tag.id not in wanted:
                wanted.append(tag.id)
        if set(wanted) != current:
            notes.append("метки")
        _set_tags(session, project_id, task.id, wanted)
    if notes:
        enqueue(
            session,
            TASK_UPDATED,
            {
                "title": task.title,
                "subject": ", ".join(dict.fromkeys(notes)),
                "project_id": project_id,
                "task_id": task.id,
                "link": "/projects/" + str(project_id) + "/tasks/" + str(task.id),
            },
            user_id=user_id,
        )
    if deadline_changed:
        enqueue(
            session,
            TASK_DEADLINE_CHANGED,
            {
                "title": "Срок изменён",
                "subject": task.title,
                "project_id": project_id,
                "task_id": task.id,
                "link": "/projects/" + str(project_id) + "/tasks/" + str(task.id),
            },
            user_id=user_id,
        )
    task.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    with log_scope("tasks", "update", user_id=user_id):
        logger.info("task updated id={} project={}", task.id, project_id)
    return _task_full(session, task)


def delete_task(session: Session, project_id: int, user_id: int, task_id: int) -> dict:
    """Мягкое удаление: задача уходит в корзину и восстановима (патч N).

    Чеклист/метки/события остаются при задаче — после восстановления
    всё на месте. Окончательно запись разбирает purge_task из корзины.
    """
    task = _task(session, project_id, task_id)
    task.deleted_at = utcnow()
    task.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        TASK_DELETED,
        {"title": "Задача удалена", "subject": task.title, "project_id": project_id, "link": "/projects/" + str(project_id)},
        user_id=user_id,
    )
    with log_scope("tasks", "delete", user_id=user_id):
        logger.info("task deleted id={} project={}", task_id, project_id)
    return {"id": task.id, "title": task.title, "deleted_at": task.deleted_at.isoformat()}


def restore_task(session: Session, project_id: int, user_id: int, task_id: int) -> dict:
    task = _task(session, project_id, task_id, in_trash=True)
    task.deleted_at = None
    task.updated_at = utcnow()
    touch_project(session, project_id)
    session.flush()
    enqueue(
        session,
        TASK_UPDATED,
        {"title": "Задача восстановлена", "subject": task.title, "project_id": project_id, "link": "/projects/" + str(project_id) + "/tasks/" + str(task.id)},
        user_id=user_id,
    )
    with log_scope("tasks", "restore", user_id=user_id):
        logger.info("task restored id={} project={}", task_id, project_id)
    return _task_full(session, task)


def purge_task(session: Session, project_id: int, user_id: int, task_id: int) -> None:
    """Окончательное удаление — только для записей из корзины."""
    task = _task(session, project_id, task_id, in_trash=True)
    for model in (ChecklistItem, TaskTag, TaskEvent):
        for row in session.scalars(select(model).where(model.task_id == task.id)).all():
            session.delete(row)
    for link in _links(session, task.id):
        session.delete(link)
    session.delete(task)
    touch_project(session, project_id)
    session.flush()
    with log_scope("tasks", "purge", user_id=user_id):
        logger.info("task purged id={} project={}", task_id, project_id)


def order_tasks(session: Session, project_id: int, user_id: int, status_id: int, ids: list[int]) -> None:
    status = _status(session, project_id, status_id)
    seen: set[int] = set()
    for position, task_id in enumerate(ids):
        if task_id in seen:
            continue
        seen.add(task_id)
        task = _task(session, project_id, task_id)
        moved = task.status_id != status.id
        task.status_id = status.id
        task.position = position
        if moved:
            task.closed_at = utcnow() if status.is_closed else None
            task.updated_at = utcnow()
            events.add_event(session, task.id, user_id, events.STATUS, status.name)
            enqueue(session, TASK_STATUS_CHANGED, _event_payload(task, status_id=status.id), user_id=user_id)
            if status.is_closed:
                recurrence.spawn_next(session, project_id, user_id, task)
    session.flush()
    with log_scope("tasks", "order", user_id=user_id):
        logger.info("tasks ordered project={} status={}", project_id, status.id)


def _set_tags(session: Session, project_id: int, task_id: int, tag_ids: list[int]) -> None:
    wanted = []
    for tag_id in tag_ids:
        tag = session.get(Tag, tag_id)
        if tag is None or tag.project_id != project_id:
            raise HTTPException(status_code=400, detail="Метка не найдена")
        if tag.id not in wanted:
            wanted.append(tag.id)
    for link in session.scalars(select(TaskTag).where(TaskTag.task_id == task_id)).all():
        session.delete(link)
    session.flush()
    for tag_id in wanted:
        session.add(TaskTag(task_id=task_id, tag_id=tag_id))
    session.flush()


def _links(session: Session, task_id: int) -> list[FileLink]:
    return list(
        session.scalars(
            select(FileLink).where(FileLink.module == "tasks", FileLink.entity_type == "task", FileLink.entity_id == task_id)
        ).all()
    )
