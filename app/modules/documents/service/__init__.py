"""Сервис документов, разбитый на тематические файлы.

Публичный API реэкспортируется отсюда целиком, поэтому внешние импорты не
меняются: ``from app.modules.documents import service`` (router, корзина,
вложения писем в документы) продолжает работать.

Раскладка по файлам:

- ``_queries.py``   — строка документа, версии, связи файлов;
- ``_validators.py`` — название и текстовые поля с лимитами;
- ``_serialize.py`` — dict-ответы: краткий, полный, версия;
- ``versions.py``   — загрузка файла в новую версию, удаление версии;
- ``crud.py``       — список, создание (в том числе из вложения), правка,
  мягкое удаление, восстановление, чистка, текст, дашборд;
- ``search.py``     — поиск для командной палитры;
- ``jobs.py``       — повтор разбора неудачных версий, проверка парсеров.
"""

from app.modules.documents.service.crud import (
    create_document,
    create_from_stored,
    dashboard_provider,
    delete_document,
    document_text,
    get_document,
    list_documents,
    purge_document,
    restore_document,
    update_document,
)
from app.modules.documents.service.jobs import ensure_parsers, retry_extract
from app.modules.documents.service.search import search_provider
from app.modules.documents.service.versions import add_version, delete_version

__all__ = [
    "add_version",
    "create_document",
    "create_from_stored",
    "dashboard_provider",
    "delete_document",
    "delete_version",
    "document_text",
    "ensure_parsers",
    "get_document",
    "list_documents",
    "purge_document",
    "restore_document",
    "retry_extract",
    "search_provider",
    "update_document",
]
