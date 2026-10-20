"""Сервис примеров, разбитый на тематические файлы.

Публичный API реэкспортируется отсюда целиком, поэтому внешние импорты
(``from app.modules.examples import service`` в router.py) не меняются.

Раскладка по файлам:

- ``_queries.py``   — строка примера, файлы, метки, потолок файлов;
- ``catalog.py``    — языки примеров из настроек;
- ``_validators.py`` — название, текст, заметка, язык, метки, фильтр;
- ``tags.py``       — метки: список, синхронизация, уборка сирот;
- ``files.py``      — прикрепление файлов и импорт файла новым примером;
- ``crud.py``       — список, создание, правка, удаление, поиск.
"""

from app.modules.examples.service.crud import (
    create_example,
    delete_example,
    get_example,
    list_examples,
    search_provider,
    update_example,
)
from app.modules.examples.service.files import add_file, delete_file, import_file
from app.modules.examples.service.tags import list_tags

__all__ = [
    "add_file",
    "create_example",
    "delete_example",
    "delete_file",
    "get_example",
    "import_file",
    "list_examples",
    "list_tags",
    "search_provider",
    "update_example",
]
