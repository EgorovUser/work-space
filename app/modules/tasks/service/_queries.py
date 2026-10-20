"""Выборки строк для модуля задач: чистое чтение без бизнес-логики.

Сюда вынесены все приватные загрузчики, которые нужны нескольким файлам
пакета. Батч-хелперы ``_checks_by_tasks`` и ``_tags_by_task`` загружают
связанные данные сразу для списка задач — на них держится исправление
N+1 в ``board.list_tasks``.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.tasks.models import ChecklistItem, Tag, Task, TaskEvent, TaskStatus, TaskTag


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


def _task(session: Session, project_id: int, task_id: int, in_trash: bool = False) -> Task:
    row = session.get(Task, task_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if in_trash and row.deleted_at is None:
        raise HTTPException(status_code=404, detail="Задача не в корзине")
    if not in_trash and row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Задача удалена в корзину")
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


def _checks(session: Session, task_id: int) -> list[ChecklistItem]:
    return list(
        session.scalars(
            select(ChecklistItem).where(ChecklistItem.task_id == task_id).order_by(ChecklistItem.position.asc(), ChecklistItem.id.asc())
        ).all()
    )


def _checks_by_tasks(session: Session, task_ids: list[int]) -> dict[int, list[ChecklistItem]]:
    result: dict[int, list[ChecklistItem]] = {task_id: [] for task_id in task_ids}
    if not task_ids:
        return result
    rows = session.scalars(
        select(ChecklistItem)
        .where(ChecklistItem.task_id.in_(task_ids))
        .order_by(ChecklistItem.task_id.asc(), ChecklistItem.position.asc(), ChecklistItem.id.asc())
    ).all()
    for row in rows:
        result.setdefault(row.task_id, []).append(row)
    return result


def _check(session: Session, task_id: int, item_id: int) -> ChecklistItem:
    row = session.get(ChecklistItem, item_id)
    if row is None or row.task_id != task_id:
        raise HTTPException(status_code=404, detail="Пункт не найден")
    return row


def _tag_out(row: Tag) -> dict:
    return {"id": row.id, "name": row.name}


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


def _events(session: Session, task_id: int) -> list[TaskEvent]:
    return list(session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id.asc())).all())
