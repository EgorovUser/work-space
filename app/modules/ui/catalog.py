"""Каталог редактируемых страниц: элементы и их свойства (патч AW).

Это контракт между хранением (``ui_configs``), нормализацией
(``service/normalize.py``) и инспектором свойств на фронте:
``PropertyPanel`` рендерится по этой схеме, а не по рукописным формам —
как инспектор SurveyJS, который сам является «формой из схемы». Новый
редактируемый элемент = декларация здесь + компонент в реестре фронта
(``frontend/src/ui/``), отдельного редактора писать не нужно.

Философия — как у настроек (``app/core/setting_defs.py``): схема живёт
на бэкенде, интерфейс рисуется по схеме, поэтому серверная валидация и
клиентский инспектор не разъезжаются. Свойства элементов — только
презентационные (раскладка и вид): поведение данных (лимиты выборки,
горизонт задач) остаётся в настройках, у «Сегодня» один источник данных
``/api/home``, и конфигурация страницы его не дублирует.

Схема страницы версионирована (``schema_version``): когда элемент или
свойство переименовывают или убирают, версию поднимают — нормализация
при загрузке выкинет забытые ключи и вольёт дефолты новых, сохранив
конфиг (whitelist-эволюция). Пикселей и свободного канваса нет:
сеточная модель (span в колонках) оставляет адаптив и e2e честными.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PropDef:
    """Одно свойство элемента в инспекторе."""

    key: str
    type: str  # "enum" | "bool" | "str"
    label: str
    group: str = "Раскладка"
    default: object = None
    options: tuple[object, ...] = ()
    ui_hint: str = ""  # "span" — селектор ширины с человеческими подписями
    max_length: int | None = None  # для строк


@dataclass(frozen=True)
class ElementDef:
    name: str
    title: str
    span: int  # ширина по умолчанию, колонок из четырёх
    props: tuple[PropDef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PageDef:
    name: str
    title: str
    schema_version: int
    elements: tuple[ElementDef, ...] = field(default_factory=tuple)


def _common(*, span: int, density: bool = False) -> tuple[PropDef, ...]:
    """Общие свойства всех элементов: ширина, скрытие, свой заголовок.

    ``density`` — у карточек-списков (строки можно рисовать плотнее).
    """
    props = [
        PropDef(
            key="span",
            type="enum",
            options=(1, 2, 3, 4),
            default=span,
            label="Ширина",
            group="Раскладка",
            ui_hint="span",
        ),
        PropDef(key="hidden", type="bool", default=False, label="Скрыть на странице", group="Раскладка"),
        PropDef(key="title", type="str", default="", label="Свой заголовок", group="Вид", max_length=80),
    ]
    if density:
        props.append(
            PropDef(
                key="density",
                type="enum",
                options=("normal", "compact"),
                default="normal",
                label="Плотность строк",
                group="Вид",
            )
        )
    return tuple(props)


TODAY = PageDef(
    name="today",
    title="Сегодня",
    schema_version=1,
    elements=(
        ElementDef(name="overdue-tasks", title="Просроченные", span=4, props=_common(span=4, density=True)),
        ElementDef(name="upcoming-tasks", title="Ближайшие сроки", span=2, props=_common(span=2, density=True)),
        ElementDef(name="pomodoro", title="Помодоро", span=2, props=_common(span=2)),
        ElementDef(name="mail-events", title="События на сегодня", span=2, props=_common(span=2, density=True)),
        ElementDef(name="new-mail", title="Новые письма", span=2, props=_common(span=2, density=True)),
        ElementDef(name="notifications", title="Уведомления", span=2, props=_common(span=2, density=True)),
        ElementDef(name="projects", title="Проекты", span=4, props=_common(span=4, density=True)),
    ),
)

PAGES: dict[str, PageDef] = {TODAY.name: TODAY}


def get_page(name: str) -> PageDef | None:
    return PAGES.get(name)


def element(page: PageDef, name: str) -> ElementDef | None:
    for item in page.elements:
        if item.name == name:
            return item
    return None


def catalog_payload(page: PageDef) -> dict:
    """Каталог для инспектора фронта: элементы и схемы их свойств."""

    def prop_payload(prop: PropDef) -> dict:
        out = {
            "key": prop.key,
            "type": prop.type,
            "label": prop.label,
            "group": prop.group,
            "default": prop.default,
        }
        if prop.options:
            out["options"] = list(prop.options)
        if prop.ui_hint:
            out["ui_hint"] = prop.ui_hint
        if prop.max_length is not None:
            out["max_length"] = prop.max_length
        return out

    return {
        "name": page.name,
        "title": page.title,
        "schema_version": page.schema_version,
        "elements": [
            {"name": item.name, "title": item.title, "span": item.span, "props": [prop_payload(p) for p in item.props]}
            for item in page.elements
        ],
    }
