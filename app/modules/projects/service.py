from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.bridge import card_summary, dashboard_blocks, home_block, inbox_items, run_project_created, search_groups
from app.core.db import utcnow
from app.core.entities import owned_row
from app.core.events_catalog import PROJECT_ARCHIVED, PROJECT_CREATED, PROJECT_UPDATED
from app.core.logging import log_scope, logger
from app.core.outbox import enqueue
from app.core.settings_store import get_bool, get_int
from app.core.text import clean_limited, clean_name
from app.modules.projects.models import Project, ProjectNote


def load_project(session: Session, project_id: int) -> Project | None:
    return session.get(Project, project_id)


def list_project_ids(session: Session) -> list[int]:
    return list(session.scalars(select(Project.id)).all())


def touch_project(session: Session, project_id: int) -> None:
    project = session.get(Project, project_id)
    if project is None:
        return
    project.updated_at = utcnow()
    session.flush()
    # Почти любая проектная мутация меняет числа бейджей (документы, секреты,
    # корзина…). Кеш счётчиков сбрасываем здесь, одним местом (патч T).
    from app.core import counters

    counters.invalidate(project_id)


def list_projects(session: Session, user_id: int, include_archived: bool) -> list[dict]:
    stmt = select(Project).order_by(Project.archived.asc(), Project.updated_at.desc(), Project.id.desc())
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    rows = session.scalars(stmt).all()
    return [_card(session, row, user_id) for row in rows]


def home(session: Session, user_id: int, task_offset: int = 0) -> dict:
    projects = list_projects(session, user_id, include_archived=False)
    ids = [item["id"] for item in projects]
    names = {item["id"]: item["name"] for item in projects}
    show_tasks = get_bool("projects", "home.show_tasks")
    show_mail = get_bool("projects", "home.show_mail")
    show_events = get_bool("projects", "home.show_events")
    show_notifications = get_bool("projects", "home.show_notifications")
    task_limit = get_int("projects", "home.task_limit")
    tasks = inbox_items("tasks", session, user_id, task_limit, ids, max(0, task_offset)) if show_tasks else []
    mail = inbox_items("mail", session, user_id, get_int("projects", "home.mail_limit"), ids) if show_mail else []
    events = inbox_items("events", session, user_id, get_int("projects", "home.event_limit"), ids) if show_events else []
    # Уведомления не делятся по проектам — это пользовательская лента,
    # поэтому идёт отдельным блоком, а не через inbox.
    notifications = home_block("notifications", session, user_id) if show_notifications else []
    for item in tasks:
        item["project_name"] = names.get(item.get("project_id"), "")
    for item in mail:
        item["project_name"] = names.get(item.get("project_id"), "")
    return {
        "projects": projects,
        "tasks": tasks,
        "mail": mail,
        "events": events,
        "notifications": notifications,
        "task_limit": task_limit,
        "task_offset": max(0, task_offset),
        "sections": {
            "tasks": show_tasks,
            "mail": show_mail,
            "events": show_events,
            "notifications": show_notifications,
        },
    }


def create_project(session: Session, user_id: int, name: str, description: str) -> dict:
    project = Project(
        name=_clean_name(name),
        description=_clean_description(description),
        archived=False,
        created_by=user_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(project)
    session.flush()
    run_project_created(session, project)
    with log_scope("projects", "create", user_id=user_id):
        logger.info("project created id={}", project.id)
    enqueue(
        session,
        PROJECT_CREATED,
        {"title": project.name, "project_id": project.id, "link": "/projects/" + str(project.id)},
        user_id=user_id,
    )
    return _card(session, project, user_id)


def update_project(session: Session, project: Project, user_id: int, fields: dict) -> dict:
    changed = False
    if "name" in fields and fields["name"] is not None:
        name = _clean_name(fields["name"])
        if name != project.name:
            project.name = name
            changed = True
    if "description" in fields and fields["description"] is not None:
        description = _clean_description(fields["description"])
        if description != project.description:
            project.description = description
            changed = True
    project.updated_at = utcnow()
    session.flush()
    if changed:
        enqueue(
            session,
            PROJECT_UPDATED,
            {"title": project.name, "project_id": project.id, "link": "/projects/" + str(project.id)},
            user_id=user_id,
        )
    with log_scope("projects", "update", user_id=user_id):
        logger.info("project updated id={}", project.id)
    return _card(session, project, user_id)


def set_archived(session: Session, project: Project, user_id: int, archived: bool) -> dict:
    project.archived = archived
    project.updated_at = utcnow()
    session.flush()
    with log_scope("projects", "archive", user_id=user_id):
        logger.info("project archived id={} archived={}", project.id, archived)
    enqueue(
        session,
        PROJECT_ARCHIVED,
        {"title": project.name, "subject": "В архиве" if archived else "Возвращён из архива", "project_id": project.id, "link": "/projects/" + str(project.id)},
        user_id=user_id,
    )
    return _card(session, project, user_id)


def project_card(session: Session, project: Project, user_id: int) -> dict:
    return _card(session, project, user_id)


def project_dashboard(session: Session, project: Project, user_id: int) -> dict:
    limits = {
        "chart_days": get_int("projects", "dashboard.chart_days", project_id=project.id),
        "recent_documents": get_int("projects", "dashboard.recent_documents", project_id=project.id),
        "recent_mail": get_int("projects", "dashboard.recent_mail", project_id=project.id),
        "upcoming_deadlines": get_int("projects", "dashboard.upcoming_deadlines", project_id=project.id),
    }
    blocks = dashboard_blocks(session, project.id, user_id, limits)
    return {
        "project": _card(session, project, user_id),
        "tasks_by_status": blocks.get("tasks_by_status"),
        "chart": blocks.get("chart"),
        "hours": blocks.get("hours"),
        "upcoming_deadlines": blocks.get("upcoming_deadlines"),
        "recent_documents": blocks.get("recent_documents"),
        "recent_mail": blocks.get("recent_mail"),
    }


def project_search(session: Session, project: Project, user_id: int, query: str) -> dict:
    text = (query or "").strip()
    minimum = get_int("projects", "search.min_length", project_id=project.id)
    if len(text) < minimum:
        raise HTTPException(status_code=400, detail="Запрос короче " + str(minimum) + " символов")
    limit = get_int("projects", "search.limit_per_group", project_id=project.id)
    with log_scope("projects", "search", user_id=user_id):
        logger.info("project search id={} length={}", project.id, len(text))
    return {
        "query": text,
        "groups": search_groups(session, project.id, user_id, text, limit),
    }


def _card(session: Session, project: Project, user_id: int) -> dict:
    summary = card_summary(session, project.id, user_id)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "archived": bool(project.archived),
        "created_by": project.created_by,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "card": {
            "show_open_tasks": get_bool("projects", "card.show_open_tasks", project_id=project.id),
            "show_overdue": get_bool("projects", "card.show_overdue", project_id=project.id),
            "show_nearest_deadline": get_bool("projects", "card.show_nearest_deadline", project_id=project.id),
            "show_hours_week": get_bool("projects", "card.show_hours_week", project_id=project.id),
            "show_new_mail": get_bool("projects", "card.show_new_mail", project_id=project.id),
        },
        "open_tasks": summary["open_tasks"],
        "overdue_tasks": summary["overdue_tasks"],
        "nearest_deadline": summary["nearest_deadline"],
        "hours_week": summary["hours_week"],
        "new_mail": summary["new_mail"],
    }


def list_notes(session: Session, project_id: int) -> list[dict]:
    rows = session.scalars(
        select(ProjectNote).where(ProjectNote.project_id == project_id).order_by(ProjectNote.updated_at.desc(), ProjectNote.id.desc())
    ).all()
    return [_note_out(row) for row in rows]


def create_note(session: Session, project_id: int, user_id: int, body: str) -> dict:
    text = _clean_note(body)
    count = session.scalar(select(func.count()).select_from(ProjectNote).where(ProjectNote.project_id == project_id)) or 0
    if count >= get_int("projects", "note.max_items"):
        raise HTTPException(status_code=400, detail="Слишком много заметок")
    now = utcnow()
    row = ProjectNote(project_id=project_id, body=text, created_at=now, updated_at=now)
    session.add(row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("projects", "note", user_id=user_id):
        logger.info("note created id={} project={}", row.id, project_id)
    return _note_out(row)


def update_note(session: Session, project_id: int, user_id: int, note_id: int, body: str) -> dict:
    row = _note(session, project_id, note_id)
    row.body = _clean_note(body)
    row.updated_at = utcnow()
    session.flush()
    touch_project(session, project_id)
    with log_scope("projects", "note", user_id=user_id):
        logger.info("note updated id={} project={}", row.id, project_id)
    return _note_out(row)


def delete_note(session: Session, project_id: int, user_id: int, note_id: int) -> None:
    row = _note(session, project_id, note_id)
    session.delete(row)
    session.flush()
    touch_project(session, project_id)
    with log_scope("projects", "note", user_id=user_id):
        logger.info("note deleted id={} project={}", note_id, project_id)


def _note(session: Session, project_id: int, note_id: int) -> ProjectNote:
    # У заметок нет корзины — удаление окончательное.
    return owned_row(
        session,
        ProjectNote,
        project_id,
        note_id,
        label="Заметка",
        not_found="Заметка не найдена",
    )


def _note_out(row: ProjectNote) -> dict:
    return {
        "id": row.id,
        "body": row.body,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _clean_note(body: str | None) -> str:
    text = (body or "").strip()
    limit = get_int("projects", "note.max_length")
    if not text:
        raise HTTPException(status_code=400, detail="Пустая заметка")
    if len(text) > limit:
        raise HTTPException(status_code=400, detail="Заметка длиннее " + str(limit) + " символов")
    return text


def _clean_name(name: str) -> str:
    return clean_name("projects", "name.max_length", name)


def _clean_description(description: str | None) -> str:
    return clean_limited("projects", "description.max_length", description, strip=False, long_prefix="Описание длиннее ")
