from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.bridge import materialize
from app.core.events_catalog import (
    TASK_ASSIGNED,
    TASK_CHECKLIST_ADDED,
    TASK_CHECKLIST_DONE,
    TASK_COMMENT,
    TASK_CREATED,
    TASK_DEADLINE_CHANGED,
    TASK_DEADLINE_SOON,
    TASK_DELETED,
    TASK_FILE,
    TASK_OVERDUE,
    TASK_STATUS_CHANGED,
    TASK_UPDATED,
)
from app.core.logging import log_scope, logger
from app.core.models import FileLink, StoredFile, User
from app.core.outbox import enqueue
from app.core.settings_store import get, get_int, get_str
from app.modules.projects.service import touch_project
from app.modules.tasks import events
from app.modules.tasks.models import ChecklistItem, Tag, Task, TaskEvent, TaskNotice, TaskRef, TaskStatus, TaskTag


def seed_project(session: Session, project) -> None:
    seed_project_id(session, project.id)


def seed_project_id(session: Session, project_id: int) -> None:
    exists = session.scalars(select(TaskStatus.id).where(TaskStatus.project_id == project_id)).first()
    if exists is not None:
        return
    raw = get("tasks", "statuses.defaults")
    if not isinstance(raw, list):
        return
    name_limit = get_int("tasks", "status.name.max_length")
    color_limit = get_int("tasks", "status.color.max_length")
    position = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        session.add(
            TaskStatus(
                project_id=project_id,
                name=name[:name_limit],
                color=str(item.get("color") or "")[:color_limit],
                is_closed=bool(item.get("is_closed")),
                position=position,
                created_at=utcnow(),
            )
        )
        position += 1
    session.flush()


def backfill_statuses() -> None:
    from app.core.db import session_scope
    from app.modules.projects.service import list_project_ids

    with session_scope() as session:
        for project_id in list_project_ids(session):
            seed_project_id(session, project_id)


def load_task(session: Session, task_id: int) -> Task | None:
    return session.get(Task, task_id)


def list_statuses(session: Session, project_id: int) -> list[dict]:
    rows = _statuses(session, project_id)
    return [_status_out(row) for row in rows]


def create_status(session: Session, project_id: int, user_id: int, name: str, color: str, is_closed: bool) -> dict:
    rows = _statuses(session, project_id)
    row = TaskStatus(
        project_id=project_id,
        name=_clean(name, "status.name.max_length", "Укажите название колонки"),
        color=_color(color),
        is_closed=is_closed,
        position=len(rows),
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("tasks", "status.create", user_id=user_id):
        logger.info("status created id={} project={}", row.id, project_id)
    return _status_out(row)


def update_status(session: Session, project_id: int, user_id: int, status_id: int, fields: dict) -> dict:
    row = _status(session, project_id, status_id)
    if "name" in fields and fields["name"] is not None:
        row.name = _clean(fields["name"], "status.name.max_length", "Укажите название колонки")
    if "color" in fields and fields["color"] is not None:
        row.color = _color(fields["color"])
    if "is_closed" in fields and fields["is_closed"] is not None:
        row.is_closed = bool(fields["is_closed"])
        _sync_closed_flags(session, project_id, row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("tasks", "status.update", user_id=user_id):
        logger.info("status updated id={} project={}", row.id, project_id)
    return _status_out(row)


def delete_status(session: Session, project_id: int, user_id: int, status_id: int) -> None:
    row = _status(session, project_id, status_id)
    used = session.scalar(select(func.count()).select_from(Task).where(Task.status_id == row.id)) or 0
    if used:
        raise HTTPException(status_code=400, detail="В колонке есть задачи")
    session.delete(row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("tasks", "status.delete", user_id=user_id):
        logger.info("status deleted id={} project={}", status_id, project_id)


def order_statuses(session: Session, project_id: int, user_id: int, ids: list[int]) -> list[dict]:
    rows = {row.id: row for row in _statuses(session, project_id)}
    if set(ids) != set(rows):
        raise HTTPException(status_code=400, detail="Передайте все колонки проекта")
    for position, status_id in enumerate(ids):
        rows[status_id].position = position
    session.flush()
    with log_scope("tasks", "status.order", user_id=user_id):
        logger.info("statuses ordered project={}", project_id)
    return [_status_out(rows[status_id]) for status_id in ids]


def list_tags(session: Session, project_id: int) -> list[dict]:
    rows = session.scalars(select(Tag).where(Tag.project_id == project_id).order_by(Tag.name.asc(), Tag.id.asc())).all()
    return [_tag_out(row) for row in rows]


def create_tag(session: Session, project_id: int, user_id: int, name: str) -> dict:
    text = _clean(name, "tag.name.max_length", "Укажите метку")
    rows = session.scalars(select(Tag).where(Tag.project_id == project_id)).all()
    if any(row.name.casefold() == text.casefold() for row in rows):
        raise HTTPException(status_code=400, detail="Такая метка уже есть")
    row = Tag(project_id=project_id, name=text)
    session.add(row)
    session.flush()
    with log_scope("tasks", "tag.create", user_id=user_id):
        logger.info("tag created id={} project={}", row.id, project_id)
    return _tag_out(row)


def delete_tag(session: Session, project_id: int, user_id: int, tag_id: int) -> None:
    row = session.get(Tag, tag_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Метка не найдена")
    for link in session.scalars(select(TaskTag).where(TaskTag.tag_id == row.id)).all():
        session.delete(link)
    session.delete(row)
    session.flush()
    with log_scope("tasks", "tag.delete", user_id=user_id):
        logger.info("tag deleted id={} project={}", tag_id, project_id)


def list_tasks(session: Session, project_id: int) -> dict:
    limit = get_int("tasks", "board.max_tasks", project_id=project_id)
    rows = session.scalars(
        select(Task).where(Task.project_id == project_id).order_by(Task.position.asc(), Task.id.asc()).limit(limit)
    ).all()
    return {"items": [_task_brief(session, row) for row in rows], "truncated": len(rows) >= limit}


def get_task(session: Session, project_id: int, task_id: int) -> dict:
    return _task_full(session, _task(session, project_id, task_id))


def create_task(session: Session, project_id: int, user_id: int, fields: dict) -> dict:
    status = _pick_status(session, project_id, fields.get("status_id"))
    priority = _priority(fields.get("priority"), project_id)
    mode = _progress_mode(fields.get("progress_mode"), project_id)
    manual = _manual(fields.get("progress_manual") or 0)
    assignee = _assignee(session, fields.get("assignee_id"))
    position = _next_position(session, status.id)
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
    if "status_id" in fields and fields["status_id"] is not None and fields["status_id"] != task.status_id:
        status = _status(session, project_id, fields["status_id"])
        task.status_id = status.id
        task.position = _next_position(session, status.id)
        task.closed_at = utcnow() if status.is_closed else None
        events.add_event(session, task.id, user_id, events.STATUS, status.name)
        enqueue(session, TASK_STATUS_CHANGED, _event_payload(task, status_id=status.id), user_id=user_id)
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


def delete_task(session: Session, project_id: int, user_id: int, task_id: int) -> None:
    task = _task(session, project_id, task_id)
    for model in (ChecklistItem, TaskTag, TaskEvent):
        for row in session.scalars(select(model).where(model.task_id == task.id)).all():
            session.delete(row)
    for link in _links(session, task.id):
        session.delete(link)
    session.delete(task)
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
    session.flush()
    with log_scope("tasks", "order", user_id=user_id):
        logger.info("tasks ordered project={} status={}", project_id, status.id)


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


def card_provider(session: Session, project_id: int, user_id: int | None) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    rows = session.execute(
        select(Task.deadline, TaskStatus.is_closed)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(Task.project_id == project_id)
    ).all()
    open_count = 0
    overdue = 0
    nearest = None
    for deadline, closed in rows:
        if closed:
            continue
        open_count += 1
        if deadline is None:
            continue
        if nearest is None or deadline < nearest:
            nearest = deadline
        if deadline.astimezone(zone).date() < today:
            overdue += 1
    return {
        "open_tasks": open_count,
        "overdue_tasks": overdue,
        "nearest_deadline": nearest.isoformat() if nearest is not None else None,
    }


def inbox_provider(session: Session, user_id: int | None, limit: int, project_ids: list[int]) -> list[dict]:
    zone = _zone()
    today = datetime.now(zone).date()
    horizon = get_int("projects", "home.horizon_days")
    cutoff = today + timedelta(days=horizon) if horizon > 0 else None
    cap = limit * 40 if cutoff is not None else limit
    rows = session.execute(
        select(Task, TaskStatus.is_closed)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(
            Task.project_id.in_(project_ids),
            Task.deadline.is_not(None),
            TaskStatus.is_closed.is_(False),
        )
        .order_by(Task.deadline.asc(), Task.id.asc())
        .limit(cap)
    ).all()
    items = []
    for task, _closed in rows:
        due = task.deadline.astimezone(zone).date()
        if cutoff is not None and due > cutoff:
            continue
        items.append(
            {
                "id": task.id,
                "project_id": task.project_id,
                "title": task.title,
                "deadline": task.deadline.isoformat(),
                "overdue": due < today,
            }
        )
        if len(items) >= limit:
            break
    return items


def dashboard_provider(session: Session, project_id: int, user_id: int | None, limits: dict) -> dict:
    return {
        "tasks_by_status": _counts(session, project_id),
        "chart": _chart(session, project_id, int(limits.get("chart_days") or 1)),
        "upcoming_deadlines": _upcoming(session, project_id, int(limits.get("upcoming_deadlines") or 1)),
    }


def search_provider(session: Session, project_id: int, user_id: int | None, query: str, limit: int) -> list[dict]:
    needle = query.casefold()
    rows = session.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.updated_at.desc())).all()
    found = []
    tags = _tags_by_task(session, [row.id for row in rows])
    for row in rows:
        hay = " ".join([row.title, row.description or "", " ".join(item["name"] for item in tags.get(row.id, []))])
        if needle in hay.casefold():
            found.append({"id": row.id, "title": row.title})
        if len(found) >= limit:
            break
    return found


def check_deadlines() -> None:
    from app.core.db import session_scope

    with session_scope() as session:
        rows = session.execute(
            select(Task, TaskStatus.is_closed)
            .join(TaskStatus, TaskStatus.id == Task.status_id)
            .where(Task.deadline.is_not(None), TaskStatus.is_closed.is_(False))
        ).all()
        zone = _zone()
        today = datetime.now(zone).date()
        for task, _closed in rows:
            due = task.deadline.astimezone(zone).date()
            days = (due - today).days
            if days < 0:
                key = "task:" + str(task.id) + ":overdue:" + today.isoformat()
                _notice(session, task, TASK_OVERDUE, key, days)
            elif days in _warn_days(task.project_id):
                key = "task:" + str(task.id) + ":deadline:" + due.isoformat() + ":" + str(days)
                _notice(session, task, TASK_DEADLINE_SOON, key, days)


def _notice(session: Session, task: Task, event_type: str, key: str, days: int) -> None:
    exists = session.scalars(select(TaskNotice.id).where(TaskNotice.dedup_key == key)).first()
    if exists is not None:
        return
    session.add(TaskNotice(dedup_key=key, task_id=task.id, event_type=event_type, created_at=utcnow()))
    payload = _event_payload(task)
    payload["days_left"] = days
    payload["dedup_key"] = key
    enqueue(session, event_type, payload, user_id=None)
    with log_scope("tasks", "deadline"):
        logger.info("deadline event type={} task={} days={}", event_type, task.id, days)


def _warn_days(project_id: int) -> set[int]:
    raw = get("tasks", "deadlines.warn_days", project_id=project_id)
    if not isinstance(raw, list):
        return set()
    return {item for item in raw if isinstance(item, int) and not isinstance(item, bool) and item >= 0}


def _counts(session: Session, project_id: int) -> list[dict]:
    rows = _statuses(session, project_id)
    counts = dict(
        session.execute(
            select(Task.status_id, func.count()).where(Task.project_id == project_id).group_by(Task.status_id)
        ).all()
    )
    return [
        {"status_id": row.id, "name": row.name, "color": row.color, "is_closed": row.is_closed, "count": int(counts.get(row.id, 0))}
        for row in rows
    ]


def _chart(session: Session, project_id: int, days: int) -> dict:
    zone = _zone()
    today = datetime.now(zone).date()
    span = max(1, days)
    labels = []
    created = []
    closed = []
    rows = session.execute(
        select(Task.created_at, Task.closed_at).where(Task.project_id == project_id)
    ).all()
    from datetime import timedelta

    for offset in range(span - 1, -1, -1):
        day = today - timedelta(days=offset)
        labels.append(day.isoformat())
        created.append(sum(1 for item in rows if item[0] is not None and item[0].astimezone(zone).date() == day))
        closed.append(sum(1 for item in rows if item[1] is not None and item[1].astimezone(zone).date() == day))
    return {"labels": labels, "created": created, "closed": closed}


def _upcoming(session: Session, project_id: int, limit: int) -> list[dict]:
    rows = session.execute(
        select(Task)
        .join(TaskStatus, TaskStatus.id == Task.status_id)
        .where(Task.project_id == project_id, Task.deadline.is_not(None), TaskStatus.is_closed.is_(False))
        .order_by(Task.deadline.asc(), Task.id.asc())
        .limit(max(1, limit))
    ).scalars().all()
    return [{"id": row.id, "title": row.title, "deadline": row.deadline.isoformat()} for row in rows]


def _task_brief(session: Session, task: Task) -> dict:
    checks = _checks(session, task.id)
    tags = _tags_by_task(session, [task.id]).get(task.id, [])
    return {
        "id": task.id,
        "project_id": task.project_id,
        "status_id": task.status_id,
        "title": task.title,
        "assignee_id": task.assignee_id,
        "priority": task.priority,
        "progress": _progress(task, checks),
        "progress_mode": task.progress_mode,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "position": task.position,
        "checklist_done": sum(1 for item in checks if item.done),
        "checklist_total": len(checks),
        "tags": tags,
        "updated_at": task.updated_at.isoformat(),
    }


def _task_full(session: Session, task: Task) -> dict:
    data = _task_brief(session, task)
    data["description"] = task.description or ""
    data["progress_manual"] = task.progress_manual
    data["created_at"] = task.created_at.isoformat()
    data["closed_at"] = task.closed_at.isoformat() if task.closed_at else None
    data["checklist"] = [_check_out(row) for row in _checks(session, task.id)]
    data["events"] = [_event_out(row) for row in _events(session, task.id)]
    data["files"] = _files(session, task.id)
    return data


def _event_out(row: TaskEvent) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "body": row.body or "",
        "user_id": row.user_id,
        "created_at": row.created_at.isoformat(),
    }


def _check_out(row: ChecklistItem) -> dict:
    return {"id": row.id, "title": row.title, "done": bool(row.done), "position": row.position}


def _status_out(row: TaskStatus) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "color": row.color,
        "is_closed": bool(row.is_closed),
        "position": row.position,
    }


def _tag_out(row: Tag) -> dict:
    return {"id": row.id, "name": row.name}


def _files(session: Session, task_id: int) -> list[dict]:
    items = [
        _ref_out(row)
        for row in session.scalars(select(TaskRef).where(TaskRef.task_id == task_id).order_by(TaskRef.id.asc())).all()
    ]
    rows = session.execute(
        select(FileLink, StoredFile)
        .join(StoredFile, StoredFile.id == FileLink.file_id)
        .where(FileLink.module == "tasks", FileLink.entity_type == "task", FileLink.entity_id == task_id)
        .order_by(FileLink.id.asc())
    ).all()
    for link, stored in rows:
        items.append(
            {
                "id": link.id,
                "kind": "file",
                "target_id": None,
                "file_id": stored.id,
                "original_name": stored.original_name,
                "size": stored.size,
            }
        )
    return items


def _ref_out(row: TaskRef) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "target_id": row.target_id,
        "file_id": row.file_id,
        "original_name": row.title,
        "size": None,
    }


def _links(session: Session, task_id: int) -> list[FileLink]:
    return list(
        session.scalars(
            select(FileLink).where(FileLink.module == "tasks", FileLink.entity_type == "task", FileLink.entity_id == task_id)
        ).all()
    )


def _events(session: Session, task_id: int) -> list[TaskEvent]:
    return list(session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id.asc())).all())


def _checks(session: Session, task_id: int) -> list[ChecklistItem]:
    return list(
        session.scalars(
            select(ChecklistItem).where(ChecklistItem.task_id == task_id).order_by(ChecklistItem.position.asc(), ChecklistItem.id.asc())
        ).all()
    )


def _check(session: Session, task_id: int, item_id: int) -> ChecklistItem:
    row = session.get(ChecklistItem, item_id)
    if row is None or row.task_id != task_id:
        raise HTTPException(status_code=404, detail="Пункт не найден")
    return row


def _tags_by_task(session: Session, task_ids: list[int]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {task_id: [] for task_id in task_ids}
    if not task_ids:
        return result
    rows = session.execute(
        select(TaskTag.task_id, Tag).join(Tag, Tag.id == TaskTag.tag_id).where(TaskTag.task_id.in_(task_ids)).order_by(Tag.name.asc())
    ).all()
    for task_id, tag in rows:
        result.setdefault(task_id, []).append(_tag_out(tag))
    return result


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


def _statuses(session: Session, project_id: int) -> list[TaskStatus]:
    return list(
        session.scalars(
            select(TaskStatus).where(TaskStatus.project_id == project_id).order_by(TaskStatus.position.asc(), TaskStatus.id.asc())
        ).all()
    )


def _status(session: Session, project_id: int, status_id: int) -> TaskStatus:
    row = session.get(TaskStatus, status_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=400, detail="Колонка не найдена")
    return row


def _task(session: Session, project_id: int, task_id: int) -> Task:
    row = session.get(Task, task_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return row


def _pick_status(session: Session, project_id: int, status_id: int | None) -> TaskStatus:
    rows = _statuses(session, project_id)
    if not rows:
        raise HTTPException(status_code=400, detail="Сначала добавьте колонку")
    if status_id is None:
        for row in rows:
            if not row.is_closed:
                return row
        return rows[0]
    return _status(session, project_id, status_id)


def _next_position(session: Session, status_id: int) -> int:
    current = session.scalar(select(func.max(Task.position)).where(Task.status_id == status_id))
    if current is None:
        return 0
    return int(current) + 1


def _assignee(session: Session, user_id: int | None) -> int | None:
    if user_id is None:
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    return user.id


def _priority(value: str | None, project_id: int) -> str:
    chosen = (value or "").strip() or get_str("tasks", "priority.default", project_id=project_id)
    allowed = _priority_ids()
    if chosen not in allowed:
        raise HTTPException(status_code=400, detail="Неизвестный приоритет")
    return chosen


def _priority_ids() -> set[str]:
    raw = get("tasks", "priorities")
    if not isinstance(raw, list):
        return set()
    return {str(item.get("id")) for item in raw if isinstance(item, dict) and item.get("id")}


def _progress_mode(value: str | None, project_id: int) -> str:
    chosen = (value or "").strip() or get_str("tasks", "progress.default", project_id=project_id)
    if chosen not in ("auto", "manual"):
        raise HTTPException(status_code=400, detail="Неизвестный режим прогресса")
    return chosen


def _manual(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=400, detail="Прогресс должен быть целым числом")
    limit = get_int("tasks", "progress.max")
    if value < 0 or value > limit:
        raise HTTPException(status_code=400, detail="Прогресс вне диапазона 0.." + str(limit))
    return value


def _progress(task: Task, checks: list[ChecklistItem]) -> int:
    limit = get_int("tasks", "progress.max")
    if task.progress_mode == "manual":
        return max(0, min(limit, int(task.progress_manual)))
    if not checks:
        return 0
    done = sum(1 for item in checks if item.done)
    return int(done * limit / len(checks))


def _deadline(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Не разобрали дату") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_zone())
    return parsed.astimezone(timezone.utc)


def _zone():
    name = get_str("core", "ui.timezone")
    if not name:
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except Exception:
        return datetime.now().astimezone().tzinfo


def _clean(value: str, key: str, empty: str) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=empty)
    limit = get_int("tasks", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Длиннее " + str(limit) + " символов")
    return text


def _text(value: str, key: str) -> str:
    text = value or ""
    limit = get_int("tasks", key)
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Длиннее " + str(limit) + " символов")
    return text


def _color(value: str) -> str:
    text = (value or "").strip()
    if not text:
        text = get_str("tasks", "status.color.default")
    limit = get_int("tasks", "status.color.max_length")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Цвет длиннее " + str(limit) + " символов")
    return text


def _sync_closed_flags(session: Session, project_id: int, status: TaskStatus) -> None:
    rows = session.scalars(select(Task).where(Task.project_id == project_id, Task.status_id == status.id)).all()
    now = utcnow()
    for task in rows:
        if status.is_closed and task.closed_at is None:
            task.closed_at = now
        if not status.is_closed:
            task.closed_at = None


def _event_payload(task: Task, status_id: int | None = None) -> dict:
    payload = {
        "task_id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "assignee_id": task.assignee_id,
        "status_id": status_id if status_id is not None else task.status_id,
    }
    if task.deadline is not None:
        payload["deadline"] = task.deadline.isoformat()
    return payload
