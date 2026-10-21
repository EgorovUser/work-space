"""Хранение конфигураций страниц: чтение, сохранение, история (патч AW).

Ревизии — по образцу секретов (``secrets/service/revisions.py``): снимок
перед каждым реальным изменением (правки без изменений историю не
засоряют), откат не разрушающий, хвост подрезается настройкой
``ui.history.keep_revisions``.

Каждое изменение публикует в шину сигнал ``ui.changed`` c именем
страницы: SSE пересылает его именованным событием, открытые вкладки
перечитывают конфиг — редактирование в одном окне тут же видно в другом.
"""

from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events_bus import publish as _bus_publish
from app.core.logging import log_scope, logger
from app.core.settings_store import get_bool, get_int
from app.modules.ui import catalog
from app.modules.ui.models import UiConfig, UiConfigRevision
from app.modules.ui.service.normalize import items_equal, normalize_items

UI_CHANGED = "ui.changed"

# Дефолт «Сегодня» уважает старые настройки видимости секций: кто выключил
# блоки настройками, получает страницу без них — как до редактора. Блок,
# выключенный настройкой, всё ещё можно добавить пикером: карточка будет
# пустой («Просроченных нет»), источник данных — настройки, раскладка —
# редактор.
_TODAY_OMIT_BY_SETTING = {
    "overdue-tasks": ("projects", "home.show_tasks"),
    "upcoming-tasks": ("projects", "home.show_tasks"),
    "mail-events": ("projects", "home.show_events"),
    "new-mail": ("projects", "home.show_mail"),
    "notifications": ("projects", "home.show_notifications"),
}


def page_state(session: Session, user_id: int, page_name: str) -> dict:
    """Эффективная конфигурация страницы + каталог для инспектора."""
    page = catalog.get_page(page_name)
    if page is None:
        raise LookupError("Неизвестная страница")
    row = _row(session, user_id, page_name)
    if row is None:
        items = default_items(page_name)
        is_default = True
    else:
        items = normalize_items(page, _load(row.data_json, page_name))
        is_default = False
    return {
        "page": page_name,
        "schema_version": page.schema_version,
        "is_default": is_default,
        "items": items,
        "catalog": catalog.catalog_payload(page),
    }


def default_items(page_name: str) -> list[dict]:
    """Элементы страницы по умолчанию — в порядке каталога.

    На «Сегодня» блоки, выключенные настройками, в дефолт не входят.
    """
    page = catalog.get_page(page_name)
    if page is None:
        raise LookupError("Неизвестная страница")
    items = []
    for element_def in page.elements:
        if page_name == "today":
            setting = _TODAY_OMIT_BY_SETTING.get(element_def.name)
            if setting and not get_bool(setting[0], setting[1]):
                continue
        item = {"element": element_def.name}
        for prop in element_def.props:
            item[prop.key] = prop.default
        items.append(item)
    return items


def save_config(session: Session, user_id: int, page_name: str, raw_items: object, actor_id: int | None) -> dict:
    """Сохранить конфиг: нормализация, снимок прежнего, сигнал вкладкам."""
    page = catalog.get_page(page_name)
    if page is None:
        raise LookupError("Неизвестная страница")
    items = normalize_items(page, raw_items)
    row = _row(session, user_id, page_name)
    if row is not None:
        if items_equal(normalize_items(page, _load(row.data_json, page_name)), items):
            # Реальных изменений нет — снимок не создаём, вкладки не дёргаем.
            with log_scope("ui", "save.noop", user_id=actor_id):
                logger.info("ui config unchanged page={}", page_name)
            return page_state(session, user_id, page_name)
        _add_revision(session, page_name, user_id, actor_id, _load(row.data_json, page_name))
        row.data_json = json.dumps(items, ensure_ascii=False)
        row.schema_version = page.schema_version
        row.updated_by = actor_id
        row.updated_at = utcnow()
    else:
        session.add(
            UiConfig(
                page=page_name,
                user_id=user_id,
                data_json=json.dumps(items, ensure_ascii=False),
                schema_version=page.schema_version,
                updated_by=actor_id,
                updated_at=utcnow(),
            )
        )
    session.flush()
    _publish(page_name, user_id)
    with log_scope("ui", "save", user_id=actor_id):
        logger.info("ui config saved page={} items={}", page_name, len(items))
    return page_state(session, user_id, page_name)


def reset_config(session: Session, user_id: int, page_name: str, actor_id: int | None) -> dict:
    """Сброс к стандартной раскладке. Снимок прежнего сохраняется —
    «ой, откатить» работает и после сброса (ревизии живут без внешнего
    ключа и переживают удаление строки конфига)."""
    page = catalog.get_page(page_name)
    if page is None:
        raise LookupError("Неизвестная страница")
    row = _row(session, user_id, page_name)
    if row is not None:
        _add_revision(session, page_name, user_id, actor_id, _load(row.data_json, page_name))
        session.delete(row)
        session.flush()
    _publish(page_name, user_id)
    with log_scope("ui", "reset", user_id=actor_id):
        logger.info("ui config reset page={}", page_name)
    return page_state(session, user_id, page_name)


def list_revisions(session: Session, user_id: int, page_name: str) -> dict:
    if catalog.get_page(page_name) is None:
        raise LookupError("Неизвестная страница")
    keep = _keep_revisions()
    rows = list(
        session.scalars(
            select(UiConfigRevision)
            .where(UiConfigRevision.page == page_name, UiConfigRevision.user_id == user_id)
            .order_by(UiConfigRevision.id.desc())
            .limit(keep)
        ).all()
    )
    items = []
    for row in rows:
        saved = _load(row.data_json, page_name)
        items.append(
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "items_count": len(saved),
                "elements": [entry.get("element", "?") for entry in saved if isinstance(entry, dict)],
            }
        )
    return {"items": items}


def restore_revision(session: Session, user_id: int, page_name: str, revision_id: int, actor_id: int | None) -> dict:
    """Откат к снимку — не разрушающий: текущее состояние тоже станет
    снимком, «Вернуть» можно жать туда-обратно сколько угодно."""
    page = catalog.get_page(page_name)
    if page is None:
        raise LookupError("Неизвестная страница")
    revision = session.scalars(
        select(UiConfigRevision).where(
            UiConfigRevision.id == revision_id,
            UiConfigRevision.page == page_name,
            UiConfigRevision.user_id == user_id,
        )
    ).one_or_none()
    if revision is None:
        raise LookupError("Ревизия не найдена")
    restored = _load(revision.data_json, page_name)
    row = _row(session, user_id, page_name)
    if row is not None:
        _add_revision(session, page_name, user_id, actor_id, _load(row.data_json, page_name))
        row.data_json = json.dumps(restored, ensure_ascii=False)
        row.schema_version = revision.schema_version
        row.updated_by = actor_id
        row.updated_at = utcnow()
    else:
        session.add(
            UiConfig(
                page=page_name,
                user_id=user_id,
                data_json=json.dumps(restored, ensure_ascii=False),
                schema_version=revision.schema_version,
                updated_by=actor_id,
                updated_at=utcnow(),
            )
        )
    session.flush()
    _publish(page_name, user_id)
    with log_scope("ui", "restore", user_id=actor_id):
        logger.info("ui config restored page={} revision={}", page_name, revision.id)
    return page_state(session, user_id, page_name)


def _row(session: Session, user_id: int, page_name: str) -> UiConfig | None:
    return session.scalars(
        select(UiConfig).where(UiConfig.page == page_name, UiConfig.user_id == user_id)
    ).one_or_none()


def _add_revision(session: Session, page_name: str, user_id: int, actor_id: int | None, items: list[dict]) -> None:
    session.add(
        UiConfigRevision(
            page=page_name,
            user_id=user_id,
            data_json=json.dumps(items, ensure_ascii=False),
            schema_version=catalog.get_page(page_name).schema_version,
            created_by=actor_id,
            created_at=utcnow(),
        )
    )
    session.flush()
    _prune_revisions(session, page_name, user_id)


def _prune_revisions(session: Session, page_name: str, user_id: int) -> None:
    keep = _keep_revisions()
    ids = list(
        session.scalars(
            select(UiConfigRevision.id)
            .where(UiConfigRevision.page == page_name, UiConfigRevision.user_id == user_id)
            .order_by(UiConfigRevision.id.desc())
        ).all()
    )
    stale = ids[keep:]
    if stale:
        session.execute(delete(UiConfigRevision).where(UiConfigRevision.id.in_(stale)))


def _keep_revisions() -> int:
    value = get_int("ui", "history.keep_revisions")
    return value if value and value > 0 else 1


def _publish(page_name: str, user_id: int) -> None:
    _bus_publish(UI_CHANGED, {"page": page_name}, user_id)


def _load(raw: str, page_name: str = "?") -> list:
    try:
        value = json.loads(raw)
    except Exception:
        with log_scope("ui", "read"):
            logger.warning("ui config ignored page={}", page_name)
        return []
    return value if isinstance(value, list) else []
