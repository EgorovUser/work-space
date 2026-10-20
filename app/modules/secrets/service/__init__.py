"""Сервис секретов, разбитый на тематические файлы.

Публичный API реэкспортируется отсюда целиком, поэтому внешние импорты не
меняются: ``from app.modules.secrets import service`` (router, корзина,
tests/test_app.py) продолжает работать.

Раскладка по файлам:

- ``_queries.py``   — строка секрета и снимка истории с проверками;
- ``catalog.py``    — виды секретов из настроек;
- ``_validators.py`` — название, лимиты, сам секрет, вид, фильтр поиска;
- ``values.py``     — шифрование/расшифровка значений;
- ``revisions.py``  — история значений: снимки, просмотр, откат;
- ``generator.py``  — генератор паролей;
- ``crud.py``       — списки, CRUD, мягкое удаление, показ значения, поиск.
"""

from app.modules.secrets.service.crud import (
    create_secret,
    delete_secret,
    get_secret,
    list_all_secrets,
    list_secrets,
    purge_secret,
    restore_secret,
    reveal_secret,
    search_provider,
    update_secret,
)
from app.modules.secrets.service.generator import generate_secret
from app.modules.secrets.service.revisions import list_revisions, restore_revision, reveal_revision

__all__ = [
    "create_secret",
    "delete_secret",
    "generate_secret",
    "get_secret",
    "list_all_secrets",
    "list_revisions",
    "list_secrets",
    "purge_secret",
    "restore_revision",
    "restore_secret",
    "reveal_revision",
    "reveal_secret",
    "search_provider",
    "update_secret",
]
