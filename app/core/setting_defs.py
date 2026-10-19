from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingDef:
    module: str
    key: str
    value_type: str
    default: object
    label: str
    description: str = ""
    allowed_scopes: tuple[str, ...] = ("global",)
    ui_hint: str = "text"
    options: tuple[str, ...] | None = None
    secret: bool = False
    public: bool = False
    restart_required: bool = False
    min_value: float | None = None
    max_value: float | None = None


def _s(**kwargs) -> SettingDef:
    return SettingDef(module="core", **kwargs)


CORE_DEFS: tuple[SettingDef, ...] = (
    _s(
        key="outbox.poll_seconds",
        value_type="int",
        default=5,
        label="Период разбора очереди событий",
        description="Секунды между проходами outbox.",
        ui_hint="number",
        min_value=1,
        max_value=3600,
    ),
    _s(
        key="outbox.max_attempts",
        value_type="int",
        default=5,
        label="Попытки обработки события",
        description="После этого событие становится failed.",
        ui_hint="number",
        min_value=1,
        max_value=50,
    ),
    _s(
        key="outbox.backoff_base_seconds",
        value_type="int",
        default=60,
        label="Базовая пауза перед повтором",
        description="Секунды. Дальше пауза удваивается.",
        ui_hint="number",
        min_value=1,
        max_value=86400,
    ),
    _s(
        key="outbox.backoff_cap_seconds",
        value_type="int",
        default=3600,
        label="Максимальная пауза повтора",
        description="Потолок экспоненциальной паузы, секунды.",
        ui_hint="number",
        min_value=1,
        max_value=86400,
    ),
    _s(
        key="outbox.batch_size",
        value_type="int",
        default=20,
        label="Событий за один проход",
        ui_hint="number",
        min_value=1,
        max_value=500,
    ),
    _s(
        key="logs.rotation_mb",
        value_type="int",
        default=10,
        label="Размер файла лога до ротации",
        description="Мегабайты. Применяется сразу.",
        ui_hint="number",
        min_value=1,
        max_value=1024,
    ),
    _s(
        key="logs.retention_days",
        value_type="int",
        default=30,
        label="Сколько дней хранить логи",
        ui_hint="number",
        min_value=1,
        max_value=3650,
    ),
    _s(
        key="logs.cleanup_interval_hours",
        value_type="int",
        default=24,
        label="Период очистки логов",
        description="Часы.",
        ui_hint="number",
        min_value=1,
        max_value=720,
    ),
    _s(
        key="files.max_upload_mb",
        value_type="int",
        default=50,
        label="Максимальный размер файла",
        description="Мегабайты.",
        ui_hint="number",
        min_value=1,
        max_value=2048,
    ),
    _s(
        key="files.allowed_extensions",
        value_type="json",
        default=[],
        label="Разрешённые расширения",
        description="Пустой список — любые файлы (ограничение не задано). Без точки, например pdf, docx.",
        ui_hint="json",
    ),
    _s(
        key="ui.app_title",
        value_type="str",
        default="Рабочее пространство",
        label="Название приложения",
        ui_hint="text",
        public=True,
    ),
    _s(
        key="ui.page_size",
        value_type="int",
        default=50,
        label="Размер страницы списков",
        allowed_scopes=("global", "user"),
        ui_hint="number",
        min_value=1,
        max_value=500,
    ),
    _s(
        key="ui.poll_notifications_seconds",
        value_type="int",
        default=30,
        label="Период опроса уведомлений",
        description="Секунды.",
        allowed_scopes=("global", "user"),
        ui_hint="number",
        min_value=1,
        max_value=3600,
    ),
    _s(
        key="ui.timezone",
        value_type="str",
        default="",
        label="Часовой пояс",
        description="Пусто — зона сервера. Например Europe/Moscow.",
        allowed_scopes=("global", "user"),
        ui_hint="text",
    ),
    _s(
        key="ui.date_format",
        value_type="str",
        default="YYYY-MM-DD HH:mm",
        label="Формат даты",
        allowed_scopes=("global", "user"),
        ui_hint="text",
    ),
    _s(
        key="ui.week_starts_on",
        value_type="int",
        default=1,
        label="Первый день недели",
        description="0 — воскресенье, 1 — понедельник.",
        allowed_scopes=("global", "user"),
        ui_hint="number",
        min_value=0,
        max_value=6,
    ),
    _s(
        key="http.outbound_timeout_seconds",
        value_type="int",
        default=20,
        label="Таймаут исходящих запросов",
        description="Секунды. Telegram и SMTP.",
        ui_hint="number",
        min_value=1,
        max_value=300,
    ),
    _s(
        key="scheduler.tick_seconds",
        value_type="int",
        default=1,
        label="Шаг планировщика",
        description="Как часто планировщик смотрит, не пора ли запустить джобу.",
        ui_hint="number",
        min_value=1,
        max_value=60,
    ),
    _s(
        key="auth.session_max_age_hours",
        value_type="int",
        default=336,
        label="Срок сессии",
        description="Часы. Новое значение применяется после перезапуска процесса.",
        ui_hint="number",
        restart_required=True,
        min_value=1,
        max_value=8760,
    ),
    _s(
        key="auth.login_max_attempts",
        value_type="int",
        default=10,
        label="Неудачных попыток входа до блокировки",
        description="На пару (логин, IP) за окно времени.",
        ui_hint="number",
        min_value=1,
        max_value=100,
    ),
    _s(
        key="auth.login_window_minutes",
        value_type="int",
        default=10,
        label="Окно для подсчёта неудачных входов",
        description="Минуты.",
        ui_hint="number",
        min_value=1,
        max_value=1440,
    ),
    _s(
        key="db.busy_timeout_ms",
        value_type="int",
        default=25000,
        label="Сколько ждать, если база занята",
        description="Миллисекунды. Новое подключение берёт это значение само.",
        ui_hint="number",
        min_value=1000,
        max_value=120000,
    ),
    _s(
        key="db.quick_check",
        value_type="bool",
        default=True,
        label="При проверке состояния смотреть целостность базы",
        description="Короткий PRAGMA quick_check. Если база повреждена, статус станет ошибкой.",
        ui_hint="checkbox",
    ),
    _s(
        key="watch.notify",
        value_type="bool",
        default=True,
        label="Писать, если в состоянии что-то сломалось",
        description="Каналы — в уведомлениях, событие «В состоянии что-то не работает». Сами уведомления, их очередь и колокольчик в это не входят.",
        ui_hint="checkbox",
    ),
    _s(
        key="watch.seconds",
        value_type="int",
        default=300,
        label="Как часто смотреть состояние, секунд",
        ui_hint="number",
        min_value=60,
        max_value=86400,
    ),
    _s(
        key="watch.remind_hours",
        value_type="int",
        default=12,
        label="Через сколько часов напомнить о той же поломке",
        ui_hint="number",
        min_value=1,
        max_value=168,
    ),
)
