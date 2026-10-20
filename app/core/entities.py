"""Загрузка строки проектной сущности: id + принадлежность проекту + корзина.

Пять модулей держали копии этого лоадера (документы, секреты, задачи,
RDP, примеры и заметки). Теперь реализация одна; в параметрах — сообщения:
окончания у «найден/удалён» в каждом модуле свои, склеивать их по шаблону
хуже, чем записать явно. Сообщение про корзину собирается из ``label``
(«Документ не в корзине») — оно одинаковое у всех.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session


def owned_row(
    session: Session,
    model,
    project_id: int,
    entity_id: int,
    *,
    label: str,
    not_found: str,
    deleted_to_trash: str | None = None,
    in_trash: bool = False,
):
    """Строка по id с проверкой принадлежности проекту.

    - чужой проект или нет строки — 404 ``not_found``;
    - ``deleted_to_trash`` не задан — у сущности нет корзины (примеры,
      заметки): проверки мягкого удаления не делаются вовсе;
    - ``in_trash=True`` ожидает удалённую строку (восстановление, чистка),
      ``in_trash=False`` — живую (списки, правка).
    """
    row = session.get(model, entity_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail=not_found)
    if deleted_to_trash is None:
        return row
    if in_trash and row.deleted_at is None:
        raise HTTPException(status_code=404, detail=label + " не в корзине")
    if not in_trash and row.deleted_at is not None:
        raise HTTPException(status_code=404, detail=deleted_to_trash)
    return row
