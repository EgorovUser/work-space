"""Счётчики для навигации (патч AA): письма — рельса и табы проекта.

Провайдеры для хаба ``app/core/counters.py``. Таб «Почта» проекта — те же
непрочитанные под правилами, что и «новые письма» в карточке проекта:
правила всех проектов грузятся одним запросом, сопоставление в памяти
(тонкие строки — без html_body и вложений, как в карточке). В ответе
каждый проект воркспейса: без совпадений — честный ноль.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.mail.models import MailMessage, MailRule
from app.modules.mail.service._matching import _row_matches
from app.modules.projects.models import Project

_THIN_COLUMNS = (
    MailMessage.from_name,
    MailMessage.from_addr,
    MailMessage.to_addr,
    MailMessage.subject,
    MailMessage.body,
)


def global_counts(session: Session, user_id: int | None = None) -> dict:
    value = session.scalar(
        select(func.count())
        .select_from(MailMessage)
        .where(MailMessage.read.is_(False), MailMessage.archived.is_(False))
    )
    return {"mail_unread": int(value or 0)}


def project_counts(session: Session) -> dict[int, dict]:
    rows = session.execute(
        select(*_THIN_COLUMNS).where(MailMessage.read.is_(False), MailMessage.archived.is_(False))
    ).all()
    grouped: dict[int, list[MailRule]] = {}
    for rule in session.scalars(select(MailRule).where(MailRule.enabled.is_(True))).all():
        grouped.setdefault(rule.project_id, []).append(rule)
    return {
        int(project_id): {"mail": sum(1 for row in rows if _row_matches(grouped.get(project_id, []), row, project_id))}
        for project_id in session.scalars(select(Project.id)).all()
    }
