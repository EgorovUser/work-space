"""Счётчики для навигации (патч AA): сколько активных примеров по проектам.

Провайдер для хаба ``app/core/counters.py``. Примеры удаляются окончательно
(без корзины), поэтому фильтр один — не в архиве. Outer join от проектов:
каждый проект попадает в ответ, даже полностью пустой.
"""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.examples.models import Example
from app.modules.projects.models import Project


def project_counts(session: Session) -> dict[int, dict]:
    active = case((Example.archived.is_(False), 1), else_=0)
    rows = session.execute(
        select(Project.id, func.sum(active))
        .outerjoin(Example, Example.project_id == Project.id)
        .group_by(Project.id)
    ).all()
    return {int(project_id): {"examples": int(count or 0)} for project_id, count in rows}
