"""Счётчики для навигации (патч AA): секреты — рельса и табы проекта.

Провайдеры для хаба ``app/core/counters.py``: глобальное число активных
секретов и по-проектное (GROUP BY на все проекты разом, outer join от
проектов — каждый проект в ответе, даже полностью пустой).
"""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.projects.models import Project
from app.modules.secrets.models import Secret


def global_counts(session: Session, user_id: int | None = None) -> dict:
    value = session.scalar(
        select(func.count())
        .select_from(Secret)
        .where(Secret.archived.is_(False), Secret.deleted_at.is_(None))
    )
    return {"secrets_total": int(value or 0)}


def project_counts(session: Session) -> dict[int, dict]:
    active = case(
        (Secret.archived.is_(False) & Secret.deleted_at.is_(None), 1),
        else_=0,
    )
    rows = session.execute(
        select(Project.id, func.sum(active))
        .outerjoin(Secret, Secret.project_id == Project.id)
        .group_by(Project.id)
    ).all()
    return {int(project_id): {"secrets": int(count or 0)} for project_id, count in rows}
