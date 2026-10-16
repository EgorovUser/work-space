from __future__ import annotations

from app.core.setting_defs import SettingDef


def _s(**kwargs) -> SettingDef:
    return SettingDef(module="mail", **kwargs)


_FIELDS = [
    {"id": "from", "label": "От кого"},
    {"id": "to", "label": "Кому"},
    {"id": "subject", "label": "Тема"},
    {"id": "body", "label": "Текст"},
]
_OPS = [
    {"id": "contains", "label": "содержит"},
    {"id": "not_contains", "label": "не содержит"},
    {"id": "equals", "label": "равно"},
]
_TAG_FIELDS = _FIELDS + [{"id": "received", "label": "Дата"}]
_TAG_OPS = _OPS + [
    {"id": "before", "label": "раньше"},
    {"id": "after", "label": "позже"},
    {"id": "on", "label": "в этот день"},
]
_NOTIFY_FIELDS = _FIELDS + [{"id": "tag", "label": "Хештег"}]
_NOTIFY_OPS = _OPS
_NOTIFY_MODES = [
    {"id": "all", "label": "Обо всех новых письмах"},
    {"id": "filter", "label": "Только если подошёл фильтр"},
]
_NOTIFY_MATCH = [
    {"id": "any", "label": "Достаточно одного условия"},
    {"id": "all", "label": "Нужны все условия сразу"},
]
_ACTIONS = [
    {"id": "keep", "label": "Сохранить"},
    {"id": "archive", "label": "Сразу в архив"},
    {"id": "skip", "label": "Не сохранять"},
]


DEFS: tuple[SettingDef, ...] = (
    _s(key="account.name.max_length", value_type="int", default=200, label="Максимальная длина названия ящика", ui_hint="number", min_value=1, max_value=500),
    _s(key="account.host.max_length", value_type="int", default=253, label="Максимальная длина сервера", ui_hint="number", min_value=1, max_value=500),
    _s(key="account.username.max_length", value_type="int", default=200, label="Максимальная длина логина", ui_hint="number", min_value=0, max_value=500),
    _s(key="account.folder.max_length", value_type="int", default=200, label="Максимальная длина имени папки", ui_hint="number", min_value=1, max_value=500),
    _s(key="account.password.max_length", value_type="int", default=500, label="Максимальная длина пароля ящика", ui_hint="number", min_value=0, max_value=4000),
    _s(key="account.error_max_chars", value_type="int", default=300, label="Сколько символов ошибки показывать", ui_hint="number", min_value=20, max_value=2000),
    _s(key="imap.default_port", value_type="int", default=993, label="Порт IMAP по умолчанию", allowed_scopes=("global", "project"), ui_hint="number", min_value=1, max_value=65535),
    _s(key="imap.default_ssl", value_type="bool", default=True, label="SSL по умолчанию", allowed_scopes=("global", "project"), ui_hint="checkbox"),
    _s(key="imap.default_folder", value_type="str", default="INBOX", label="Папка по умолчанию", allowed_scopes=("global", "project")),
    _s(key="imap.timeout_seconds", value_type="int", default=20, label="Таймаут IMAP, секунд", allowed_scopes=("global", "project"), ui_hint="number", min_value=3, max_value=120),
    _s(key="fetch.initial_limit", value_type="int", default=20, label="Сколько последних писем брать при первом заходе", allowed_scopes=("global", "project"), ui_hint="number", min_value=1, max_value=500),
    _s(key="fetch.batch_size", value_type="int", default=30, label="Писем в одной порции", description="Столько ещё не скачанных писем забирается за один заход к серверу.", allowed_scopes=("global",), ui_hint="number", min_value=1, max_value=200),
    _s(key="fetch.batches_per_run", value_type="int", default=4, label="Порций за один проход джобы", description="Джоба сама повторяет порцию столько раз, пока есть нескачанные письма.", ui_hint="number", min_value=1, max_value=20),
    _s(key="fetch.backfill", value_type="bool", default=True, label="Докачивать ещё не скачанные письма", ui_hint="checkbox"),
    _s(key="fetch.lookback_days", value_type="int", default=7, label="Проверять письма за сколько дней", description="Каждый забор сверяет ящик за это окно и докачивает то, чего ещё нет. 1 — только сегодня, 7 — неделя, не больше 30.", allowed_scopes=("global",), ui_hint="number", min_value=1, max_value=30),
    _s(key="fetch.notify_new", value_type="bool", default=True, label="Уведомлять о новых письмах", description="Старые порции молчат. Кого именно из новых писем поднимать — решает фильтр на вкладке почты «Уведомления».", ui_hint="checkbox"),
    _s(key="filters.move", value_type="bool", default=True, label="Письмо фильтра переносить в папку проекта", description="Письмо сохраняется всегда. Фильтр значит: это письмо проекта, и его надо перенести в папку с именем проекта.", ui_hint="checkbox"),
    _s(key="filters.notify", value_type="bool", default=True, label="Уведомлять, когда письмо отнесли к проекту", ui_hint="checkbox"),
    _s(key="message.max_bytes", value_type="int", default=15000000, label="Максимальный размер письма, байт", ui_hint="number", min_value=1000, max_value=50000000),
    _s(key="message.subject.max_length", value_type="int", default=500, label="Сколько символов темы хранить", ui_hint="number", min_value=1, max_value=4000),
    _s(key="message.address.max_length", value_type="int", default=300, label="Сколько символов адреса хранить", ui_hint="number", min_value=1, max_value=2000),
    _s(key="message.body.max_chars", value_type="int", default=20000, label="Сколько символов текста хранить", ui_hint="number", min_value=100, max_value=500000),
    _s(key="message.html.max_chars", value_type="int", default=150000, label="Сколько символов вёрстки письма хранить", ui_hint="number", min_value=1000, max_value=500000),
    _s(key="events.per_message", value_type="int", default=10, label="Сколько событий брать из одного письма", ui_hint="number", min_value=1, max_value=50),
    _s(key="events.remind", value_type="bool", default=True, label="Напоминать о событиях из почты", description="Пишет «сегодня» один раз в день события и «скоро» за указанное число часов. Каналы — в уведомлениях, события называются «События из почты».", ui_hint="checkbox"),
    _s(key="events.warn_hours", value_type="int", default=2, label="За сколько часов писать «скоро»", ui_hint="number", min_value=0, max_value=168),
    _s(key="events.grace_minutes", value_type="int", default=30, label="Сколько минут после начала ещё писать «скоро»", description="Если сервер в этот момент не работал, напоминание всё равно уйдёт.", ui_hint="number", min_value=0, max_value=240),
    _s(key="events.check_seconds", value_type="int", default=300, label="Как часто проверять события из почты, секунд", ui_hint="number", min_value=30, max_value=86400),
    _s(key="message.empty_subject", value_type="str", default="(без темы)", label="Подпись пустой темы", allowed_scopes=("global", "project")),
    _s(key="message.mark_read_on_open", value_type="bool", default=True, label="Открытие письма помечает его прочитанным", allowed_scopes=("global", "project"), ui_hint="checkbox"),
    _s(
        key="body.encodings",
        value_type="json",
        default=["utf-8", "cp1251", "koi8-r", "latin-1"],
        label="Кодировки текста письма",
        ui_hint="json",
    ),
    _s(key="list.limit", value_type="int", default=100, label="Писем в списке", allowed_scopes=("global", "project"), ui_hint="number", min_value=1, max_value=2000),
    _s(key="list.scan_limit", value_type="int", default=400, label="Сколько писем просматривать для фильтра проекта", allowed_scopes=("global", "project"), ui_hint="number", min_value=1, max_value=5000),
    _s(key="list.preview_chars", value_type="int", default=180, label="Символов текста в списке", allowed_scopes=("global", "project"), ui_hint="number", min_value=0, max_value=2000),
    _s(key="search.snippet_chars", value_type="int", default=160, label="Символов фрагмента в поиске", allowed_scopes=("global", "project"), ui_hint="number", min_value=20, max_value=1000),
    _s(key="search.include_archived", value_type="bool", default=False, label="Искать в архивных письмах", allowed_scopes=("global", "project"), ui_hint="checkbox"),
    _s(key="rules.fields", value_type="json", default=_FIELDS, label="Поля правил", allowed_scopes=("global", "project"), ui_hint="json"),
    _s(key="rules.ops", value_type="json", default=_OPS, label="Операции правил", allowed_scopes=("global", "project"), ui_hint="json"),
    _s(key="rules.actions", value_type="json", default=_ACTIONS, label="Не используется: письмо сохраняется всегда", description="Фильтр больше не выбирает сохранить или пропустить. Совпадение относит письмо к проекту.", allowed_scopes=("global", "project"), ui_hint="json"),
    _s(key="rules.default_action", value_type="str", default="keep", label="Не используется", description="Письмо сохраняется всегда, даже если ни один фильтр не подошёл.", allowed_scopes=("global", "project")),
    _s(
        key="rules.notify_actions",
        value_type="json",
        default=["keep"],
        label="Для каких действий писать событие о новом письме",
        allowed_scopes=("global", "project"),
        ui_hint="json",
    ),
    _s(key="rules.casefold", value_type="bool", default=True, label="Правила без учёта регистра", allowed_scopes=("global", "project"), ui_hint="checkbox"),
    _s(key="rule.name.max_length", value_type="int", default=200, label="Максимальная длина названия правила", ui_hint="number", min_value=1, max_value=500),
    _s(key="rule.value.max_length", value_type="int", default=500, label="Максимальная длина значения правила", ui_hint="number", min_value=1, max_value=4000),
    _s(key="tags.name.max_length", value_type="int", default=80, label="Максимальная длина названия хештега", ui_hint="number", min_value=1, max_value=200),
    _s(key="tags.fields", value_type="json", default=_TAG_FIELDS, label="Поля хештега", description="Как фильтр проекта, плюс дата получения.", ui_hint="json"),
    _s(key="tags.ops", value_type="json", default=_TAG_OPS, label="Условия хештега", ui_hint="json"),
    _s(key="tags.default_color", value_type="str", default="#3a6ea5", label="Цвет нового хештега", description="HEX, например #3a6ea5. На форме цвет можно выбрать любой.", allowed_scopes=("global",)),
    _s(key="notify.mode", value_type="str", default="all", options=("all", "filter"), label="О каких письмах уведомлять", description="all — каждое новое. filter — только если подошло условие: хештег, отправитель и другие поля.", ui_hint="text"),
    _s(key="notify.match", value_type="str", default="any", options=("any", "all"), label="Как совмещать условия фильтра уведомлений", description="any — достаточно одного. all — нужны все сразу.", ui_hint="text"),
    _s(key="notify.gate_filed", value_type="bool", default=True, label="Тот же фильтр для письма, ушедшего в проект", description="Если выключено, «письмо в проекте» приходит независимо от фильтра. «Новое письмо» фильтруется всегда, когда режим не «обо всех».", ui_hint="checkbox"),
    _s(key="notify.modes", value_type="json", default=_NOTIFY_MODES, label="Подписи режимов фильтра уведомлений", ui_hint="json"),
    _s(key="notify.matches", value_type="json", default=_NOTIFY_MATCH, label="Подписи сочетания условий", ui_hint="json"),
    _s(key="notify.fields", value_type="json", default=_NOTIFY_FIELDS, label="Поля фильтра уведомлений", ui_hint="json"),
    _s(key="notify.ops", value_type="json", default=_NOTIFY_OPS, label="Условия фильтра уведомлений", ui_hint="json"),
    _s(key="threads.enabled", value_type="bool", default=True, label="Склеивать письма одной переписки", description="Одинаковая тема, без Re: и Fwd:, — одна строка в списке. Внутри письма остаются по отдельности.", ui_hint="checkbox"),
    _s(
        key="threads.prefixes",
        value_type="json",
        default=["re", "fw", "fwd", "aw", "wg", "sv", "vs", "ответ", "отв", "пересылка", "пересл", "на", "автоматический ответ", "automatic reply"],
        label="Приставки ответа и пересылки",
        description="Снимаются с начала темы, пока тема не станет голой. Регистр не важен.",
        ui_hint="json",
    ),
    _s(key="threads.strip_passes", value_type="int", default=6, label="Сколько раз снимать приставку с темы", ui_hint="number", min_value=1, max_value=20),
    _s(key="threads.group_empty", value_type="bool", default=False, label="Склеивать письма без темы", ui_hint="checkbox"),
    _s(key="threads.scan_limit", value_type="int", default=5000, label="Сколько писем смотреть, чтобы собрать переписку", ui_hint="number", min_value=50, max_value=50000),
    _s(key="threads.show_limit", value_type="int", default=40, label="Сколько писем переписки показывать внутри", ui_hint="number", min_value=2, max_value=200),
    _s(key="job.enabled", value_type="bool", default=True, label="Самой забирать ещё не скачанные письма", ui_hint="checkbox"),
    _s(key="job.seconds", value_type="int", default=120, label="Как часто сама забирать почту, секунд", description="Кнопка не нужна: джоба сама берёт следующую порцию нескачанных писем.", ui_hint="number", min_value=30, max_value=86400),
)
