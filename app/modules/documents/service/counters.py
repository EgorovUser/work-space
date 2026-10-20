"""Счётчики для навигации (патч AA): сколько активных документов по проектам.

Провайдер для хаба ``app/core/counters.py``: один GROUP BY на все проекты
от таблицы проектов (outer join) — в ответе каждый проект воркспейса,
включая полностью пустые: «нет поля» и «ноль» не должны различаться.
"""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.projects.models import Project


def project_counts(session: Session) -> dict[int, dict]:
    active = case(
        (Document.archived.is_(False) & Document.deleted_at.is_(None), 1),
        else_=0,
    )
    rows = session.execute(
        select(Project.id, func.sum(active))
        .outerjoin(Document, Document.project_id == Project.id)
        .group_by(Project.id)
    ).all()
    return {int(project_id): {"documents": int(count or 0)} for project_id, count in rows}
