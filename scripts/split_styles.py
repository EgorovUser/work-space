"""Патч AP: механическая нарезка styles.css (1801 строка) на styles/*.css.

Правила нарезки (главное — каскад 1:1):

- границы проходят ТОЛЬКО между top-level правилами (проверено вручную);
- порядок правил не меняется никак — ни внутри файлов, ни между ними;
- styles.css становится индексом из @import в исходном порядке
  (postcss-import инлайнит их в тот же порядок в бандле);
- в каждый файл добавляется одна строка-заголовок (CSS-комментарий
  на каскад не влияет).

Запуск: python scripts/split_styles.py  (из корня репозитория)
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "frontend" / "src" / "styles.css"
TARGET = ROOT / "frontend" / "src" / "styles"

# (имя файла, первая строка, последняя строка) — 1-индексировано, включительно.
RANGES = [
    ("base", 1, 96),  # токены :root, тёмная тема, ресет
    ("shell", 98, 261),  # каркас: .app, рельса, шапка, фокус-строка
    ("layout", 263, 373),  # .page, контейнеры, табы проекта
    ("controls", 375, 527),  # карточки, кнопки, поля, списки-строки
    ("lists", 528, 717),  # табы-чипы, multi, поповеры, login, setting
    ("today", 719, 763),  # сетка «Сегодня», сводка недель
    ("board", 764, 1018),  # канбан, карточка задачи, .tc-*
    ("mail", 1019, 1128),  # почта master-detail, тулбар письма
    ("feedback", 1130, 1316),  # тосты, колокольчик, бейджи, сниппеты
    ("responsive", 1318, 1359),  # общий адаптив 800px
    ("states", 1361, 1403),  # скелетоны и пустые состояния
    ("focus", 1405, 1491),  # помодоро-чип/карточка, пикер, rdp-tools
    ("search", 1493, 1609),  # глобальный поиск в шапке
    ("calendar", 1611, 1719),  # календарь задач
    ("pwa", 1721, 1801),  # нижняя навигация, тач-таргеты
]

DESCRIPTIONS = {
    "base": "токены тем (:root, dark) и ресет",
    "shell": "каркас: рельса, шапка, фокус-строка",
    "layout": "страницы, контейнеры, табы проекта",
    "controls": "карточки, кнопки, поля, списочные строки",
    "lists": "табы-чипы, мультиселект, поповеры, формы входа/настроек",
    "today": "сетка «Сегодня» и сводка недель",
    "board": "доска задач: канбан, карточка, списание часов",
    "mail": "почта: список и читалка рядом",
    "feedback": "тосты, колокольчик, бейджи-количества",
    "responsive": "общий адаптив до 800px",
    "states": "скелетоны загрузки и пустые состояния",
    "focus": "помодоро и выбор задачи, rdp-инструменты",
    "search": "глобальный поиск в шапке",
    "calendar": "календарь задач",
    "pwa": "нижняя навигация PWA и тач-таргеты",
}


def main() -> None:
    lines = CSS.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    expected_last = RANGES[-1][2]
    if total != expected_last:
        raise SystemExit(f"styles.css: {total} строк, а серия ждёт {expected_last} — границы устарели")

    # Контроль непрерывности: диапазоны покрывают файл без наложений,
    # пропуски — только пустые строки-разделители.
    previous_end = 0
    for name, start, end in RANGES:
        for skipped in range(previous_end + 1, start):
            text = lines[skipped - 1].strip()
            if text:
                raise SystemExit(f"между секциями потерялась строка {skipped}: {text!r}")
        previous_end = end

    TARGET.mkdir(exist_ok=True)
    for name, start, end in RANGES:
        chunk = lines[start - 1 : end]
        header = f"/* {DESCRIPTIONS[name]} — кусок бывшего styles.css (патч AP). */\n"
        body = "\n".join(chunk).rstrip("\n") + "\n"
        (TARGET / f"{name}.css").write_text(header + body, encoding="utf-8")
        print(f"styles/{name}.css: строки {start}–{end} ({end - start + 1})")

    index = ["/* Глобальные стили — индекс (патч AP).", ""]
    index.append("Механическая нарезка бывшего монолита: правила не переставлялись,")
    index.append("порядок каскада = порядок @import ниже. Vite (postcss-import) инлайнит")
    index.append("файлы в бандл в этом же порядке. Новая секция — новый файл в styles/,")
    index.append("правка чужой секции — в её файле, порядок не трогаем.")
    index.append("*/")
    index.append("")
    for name, _, _ in RANGES:
        index.append(f'@import "./styles/{name}.css";')
    CSS.write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"styles.css → индекс из {len(RANGES)} @import")


if __name__ == "__main__":
    main()
