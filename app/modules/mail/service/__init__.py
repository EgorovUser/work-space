"""Сервис почты, разбитый на тематические файлы.

Публичный API и служебные имена реэкспортируются отсюда целиком,
поэтому внешние импорты не меняются:

- ``from app.modules.mail import service`` (router.py, status_check.py) —
  ``service.mailbox``, ``service._account_any`` и прочие имена работают как раньше;
- ``from app.modules.mail.service import schedule_accounts`` (status_check.py) —
  тоже работает;
- ``from app.modules.mail.service import _fold_subject, _letter_matches_notify,
  _lookback_token`` (tests/test_app.py) — тоже работает.

Раскладка по файлам (снизу вверх по слоям, циклических импортов нет):

- ``_settings.py``  — настройки, валидация, пароли, время, разбор ошибок;
- ``_matching.py``  — примитивы сопоставления письма с правилами;
- ``_queries.py``   — приватные выборки строк и отбор под правила проекта;
- ``_serialize.py`` — построение dict-ответов;
- ``_threads.py``   — свёртка тем и группировка тредов;
- ``_tags.py``      — хештеги: каталог, правила, раскраска списков;
- ``notify.py``     — уведомления: режимы, условия, CRUD;
- ``ingest.py``     — загрузка писем, события, раскладка по проектам
  (вставка через ``add_message_safe`` — защита от гонки дублей);
- ``rules.py``      — CRUD правил раскладки;
- ``accounts.py``   — ящики: CRUD, проверки, забор писем, бэкфилл, переносы;
- ``messages.py``   — ящик/списки/карточка письма, CRUD, импорт файла;
- ``providers.py``  — провайдеры дашборда/инбокса/поиска, пробы, джобы;
- ``schema.py``     — доколонки схемы (ensure_schema).
"""

from app.modules.mail.service._matching import _haystack, _matches, _row_matches
from app.modules.mail.service._queries import (
    _account,
    _account_any,
    _accounts,
    _all_accounts,
    _matching_messages,
    _message,
    _rules,
)
from app.modules.mail.service._serialize import (
    _account_out,
    _attachment_items,
    _clip_text,
    _message_out,
    _meta,
    _rule_out,
    _search_blob,
    _snippet,
    _sync_info,
    _title,
)
from app.modules.mail.service._settings import (
    _choice,
    _choices,
    _clean,
    _clip,
    _error_text,
    _folder,
    _format_when,
    _is_auth,
    _label,
    _limits,
    _lookback_token,
    _pack,
    _password,
    _port,
    _ssl,
    _timeout,
    _unpack,
    _zone,
)
from app.modules.mail.service._tags import (
    _attach_tags,
    _row_tag_keys,
    _tag_catalog,
    _tag_color,
    _tag_pair,
    _tag_out,
    _tag_rule_matches,
    _tag_value_matches,
    create_tag,
    delete_tag,
    tag_page,
)
from app.modules.mail.service._threads import (
    _clean_subject,
    _fold_subject,
    _grouped_messages,
    _strip_prefix,
    _subject_key,
    _thread_out,
    _thread_prefixes,
)
from app.modules.mail.service.accounts import (
    _backfill,
    _backfill_state,
    _block,
    _fetch_row,
    _run_moves,
    _store_batch,
    check_account,
    create_account,
    delete_account,
    fetch_account,
    place_message,
    poll_accounts,
    test_account,
    update_account,
)
from app.modules.mail.service.ingest import (
    _file_message,
    _file_one,
    _file_project,
    _ingest,
    _notify_event,
    _remember_attachments,
    _remember_events,
)
from app.modules.mail.service.messages import (
    _message_list,
    attachment_to_document,
    delete_message,
    download_attachment,
    get_message,
    import_raw,
    mailbox,
    project_mail,
    set_message_tag,
    update_message,
)
from app.modules.mail.service.notify import (
    _filed_matches_notify,
    _letter_matches_notify,
    _notify_pair,
    _notify_rule_matches,
    _notify_rule_out,
    _notify_tag_value,
    create_notify_rule,
    delete_notify_rule,
    notify_state,
    save_notify,
)
from app.modules.mail.service.providers import (
    card_provider,
    dashboard_provider,
    events_today,
    inbox_provider,
    probe_accounts,
    probe_events,
    remind_events,
    schedule_accounts,
    search_provider,
)
from app.modules.mail.service.rules import create_rule, delete_rule, update_rule

__all__ = [
    "check_account",
    "create_account",
    "create_notify_rule",
    "create_rule",
    "create_tag",
    "delete_account",
    "delete_message",
    "delete_notify_rule",
    "delete_rule",
    "delete_tag",
    "download_attachment",
    "events_today",
    "fetch_account",
    "get_message",
    "import_raw",
    "mailbox",
    "notify_state",
    "place_message",
    "poll_accounts",
    "project_mail",
    "remind_events",
    "save_notify",
    "schedule_accounts",
    "set_message_tag",
    "tag_page",
    "test_account",
    "update_account",
    "update_message",
    "update_rule",
    # приватные имена, которые используют router/status_check/тесты
    "_account_any",
    "_fold_subject",
    "_letter_matches_notify",
    "_lookback_token",
    # провайдеры
    "card_provider",
    "dashboard_provider",
    "inbox_provider",
    "probe_accounts",
    "probe_events",
    "search_provider",
]
