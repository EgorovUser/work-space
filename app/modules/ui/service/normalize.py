"""Нормализация конфига страницы по каталогу (патч AW).

Каждая загрузка сохранённого конфига прогоняется через нормализацию:

- ключей из схемы нет — долой (переименовали/убрали свойство);
- новые ключи появились — влить дефолты;
- значение не из списка/не того типа — дефолт (кривой конфиг никогда
  не ломает страницу);
- элементы с неизвестным именем сохраняются заглушками — стиль Home
  Assistant «card not found»: конфиг не портим, фронт рисует карточку-
  заглушку, откат приложения к старой версии каталога ничего не теряет;
- дубликаты известного элемента не проходят: на «Сегодня» элемент
  уникален и служит собственным идентификатором.

Нормализация только читает: результат записывается обратно при
следующем сохранении, эволюция схемы не требует миграций данных.
"""

from __future__ import annotations

from app.modules.ui.catalog import PageDef, element

_MISSING = object()


def normalize_settings(page: PageDef, raw: object) -> dict:
    """Настройки страницы по той же схеме, что и элементы: ключей из
    схемы нет — долой, новые — дефолты, мусорные значения — дефолты."""
    if not isinstance(raw, dict):
        return {prop.key: prop.default for prop in page.settings}
    out: dict = {}
    for prop in page.settings:
        out[prop.key] = _prop_value(prop, raw.get(prop.key, _MISSING))
    return out


def normalize_items(page: PageDef, raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    items: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("element")
        if not isinstance(name, str) or not name:
            continue
        if element(page, name) is None:
            # Неизвестный элемент — заглушка с общими свойствами раскладки.
            items.append(
                {
                    "element": name,
                    "span": _int_or(entry.get("span"), 4, 1, 4),
                    "height": _height_or(entry.get("height")),
                    "hidden": _bool_or(entry.get("hidden"), False),
                }
            )
            continue
        if name in seen:
            continue
        seen.add(name)
        item: dict = {"element": name}
        for prop in element(page, name).props:
            item[prop.key] = _prop_value(prop, entry.get(prop.key, _MISSING))
        items.append(item)
    return items


def configs_equal(left: dict, right: dict) -> bool:
    """Сравнение конфига на «реальное изменение»: и настройки страницы,
    и элементы; порядок элементов важен, лишние ключи сравниваемых
    нормализованных конфигов нет."""
    return left.get("settings") == right.get("settings") and left.get("items") == right.get("items")


def _prop_value(prop, value) -> object:
    if value is _MISSING:
        return prop.default
    if prop.type == "enum":
        for option in prop.options:
            if type(option) is type(value) and option == value:
                return value
        return prop.default
    if prop.type == "bool":
        return value if isinstance(value, bool) else prop.default
    if prop.type == "str":
        if not isinstance(value, str):
            return prop.default
        cleaned = value.strip()
        if prop.max_length is not None and len(cleaned) > prop.max_length:
            cleaned = cleaned[: prop.max_length]
        return cleaned
    return prop.default


def _height_or(value) -> str:
    if value in ("auto", "low", "medium", "tall"):
        return value
    return "auto"


def _int_or(value, fallback: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return min(high, max(low, value))


def _bool_or(value, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback
