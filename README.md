# Рабочее пространство

Личное приложение для одного человека: проекты и доска задач, документы, примеры, секреты, общая почта, учёт времени и уведомления. Всё крутится одним процессом. Отдельных очередей, Redis и PostgreSQL нет.

## Стек

- Python 3.12, FastAPI (обычные sync-эндпоинты), SQLAlchemy 2, SQLite в режиме WAL
- Vue 3, Vite, vue-router, обычный JavaScript. Состояние — composables, без Pinia
- Стили — свой CSS. Перетаскивание — SortableJS, графики — Chart.js
- Разбор файлов: python-docx, PyMuPDF, openpyxl
- Шифрование секретов и паролей ящика — Fernet (`cryptography`). Пароли входа — bcrypt

База — файл `data/app.db`. Схемой управляет Alembic: при старте `init_db()` создаёт таблицы на свежей базе (`create_all` + `stamp("head")`), подтягивает реальные миграции на базах, созданных до появления Alembic, и делает `upgrade("head")` на управляемых базах. Если модели и фактическая схема разошлись, в лог пишется предупреждение о дрейфе. Новые колонки и индексы оформляются миграцией в `alembic/versions/`. Файлы лежат в `data/files`: имя каталога — первые два символа sha256, сам файл — полный хеш. Повторная загрузка тех же байтов новую копию не создаёт.

Поведение (интервалы, лимиты, подписи, колонки по умолчанию) берётся из настроек. В `.env` только то, без чего процесс не живёт: ключи, каталог данных, уровень логов и учётка первого пользователя.

## Бэкап и восстановление

Скрипт `scripts/backup.sh` делает консистентную копию SQLite через `.backup` (не простое копирование файла при живом WAL), плюс `data/files/` и `.env`. Архив кладётся в `data/backups/work-space-YYYYMMDD-HHMM.tar.gz`. Хранится последние N копий (переменная `BACKUP_KEEP`, по умолчанию 7).

```bash
cd ~/work-space
./scripts/backup.sh
```

**Восстановление:**

1. Остановите контейнер: `docker compose down`
2. Распакуйте архив во временную папку и перенесите содержимое:
   ```bash
   mkdir -p /tmp/restore && tar -xzf data/backups/work-space-....tar.gz -C /tmp/restore
   cp /tmp/restore/data/app.db data/app.db
   rm -rf data/files && cp -a /tmp/restore/data/files data/files
   cp /tmp/restore/.env .env
   ```
3. Проверьте целостность: `sqlite3 data/app.db "PRAGMA integrity_check;"` (должно быть `ok`)
4. Запустите: `docker compose up -d`

Джоба очистки логов не трогает `data/backups`.

## Каталоги

```text
app/                 бэкенд
  core/              конфиг, база, вход, файлы, настройки, очередь, планировщик
  modules/           projects, tasks, documents, examples, secrets, rdp, timetracking, mail, notifications, trash
alembic/             миграции схемы (Alembic)
frontend/            Vue-интерфейс
data/                база, файлы, логи, bootstrap.env (создаётся само)
tests/               проверки бэкенда на временной базе
scripts/             вспомогательные скрипты (backup.sh)
```

Настройки бывают трёх областей: общие, проекта и пользователя. Секретные значения (токен бота, пароль SMTP, пароль ящика) в интерфейсе не показываются обратно: пустое поле при сохранении их не затирает.

## Разработка на Windows

Нужны Python 3.12 и Node.js. Два терминала из корня проекта.

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bat
cd frontend
npm install
npm run dev
```

Интерфейс: `http://localhost:8080`. Vite проксирует `/api` и `/healthz` на порт 8000.

Если `.env` нет, в режиме dev ключи создаются сами и пишутся в `data/bootstrap.env`. Первый пользователь берётся из `SEED_USERNAME` и `SEED_PASSWORD`. Если пароль не задан — `admin` / `admin`, и в лог пишется предупреждение. Свои значения — скопировать `.env.example` в `.env`.

## Тесты

Бэкенд: `pip install -r requirements.txt -r requirements-dev.txt`, затем `python -m unittest discover -s tests` — 195 проверок на временной базе (юнит-ядро, HTTP-слой через TestClient, санитайзер писем).

Фронтенд: `cd frontend && npm install && npm test`.

GitHub Actions (`.github/workflows/ci.yml`) гоняет оба набора на каждый пуш и pull request.

## Деплой на Ubuntu

На сервере нужны Docker и плагин Compose (`docker compose version` должен ответить). Репозиторий уже склонирован — дальше из его каталога.

```bash
cd ~/work-space
apt-get update
apt-get install -y docker.io docker-compose-v2 sqlite3
systemctl enable --now docker
```

Имена пакетов на Debian такие же. Если `docker compose` уже есть, установку пропускают. `sqlite3` нужен для скрипта бэкапа.

Дальше ключи и файл окружения. `SECRET_KEY` — любая длинная случайная строка. `FERNET_KEY` — ключ Fernet, не обычный пароль: им шифруются секреты, пароль ящика и SMTP. Потерять его нельзя, иначе старые записи не прочитаются. `SEED_PASSWORD` нужен только при первом запуске, когда в базе ещё нет пользователей. Потом смена этой строки вход не меняет.

```bash
cd ~/work-space
cp .env.example .env
python3 - <<'PY'
import secrets
print("SECRET_KEY=" + secrets.token_urlsafe(32))
PY
docker run --rm python:3.12-slim bash -c "pip install -q cryptography && python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
```

Первая команда печатает `SECRET_KEY`. Вторая — сам ключ Fernet, его надо вписать в строку `FERNET_KEY=`. Пакет `cryptography` на хосте для этого не нужен.

В `.env` должны быть свои значения, не заглушки из примера:

```env
APP_ENV=prod
SECRET_KEY=сюда-длинная-случайная-строка
FERNET_KEY=сюда-ключ-fernet
DATA_DIR=./data
DATABASE_URL=
LOG_LEVEL=INFO
SEED_USERNAME=admin
SEED_PASSWORD=сюда-пароль-первого-входа
```

`DATA_DIR=./data` внутри контейнера — это `/app/data`. Compose монтирует туда каталог `./data` с сервера, поэтому база и файлы переживают пересборку. Процесс внутри контейнера всегда слушает `8000`. Наружу compose публикует его как `8088` (`"8088:8000"`). `HOST` и `PORT` образ не читает. В браузере — `http://IP-СЕРВЕРА:8088`. Проверка здоровья внутри контейнера по-прежнему ходит на `127.0.0.1:8000`.

Сборка и запуск. Первый раз качает образы Node и Python и ставит зависимости, это несколько минут.

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

В логе должно появиться `application ready` и строка про созданного пользователя. Выход из логов — Ctrl+C, контейнер при этом не останавливается.

Проверка с самого сервера:

```bash
curl -sS http://127.0.0.1:8088/healthz
```

В браузере — `http://IP-СЕРВЕРА:8088`, логин и пароль из `SEED_USERNAME` / `SEED_PASSWORD`. Сессия ставится и по обычному HTTP: `https_only` выключен. Если страница не открывается снаружи, порт закрыт файрволом:

```bash
ufw allow 8088/tcp
```

Логи приложения, не демона Docker: `data/logs/app.log` и `data/logs/errors.log` на хосте. База — `data/app.db`, вложения — `data/files`. Этот каталог в git не входит, его надо хранить и бэкапить вместе с `.env`.

Обновление после новых коммитов:

```bash
cd ~/work-space
git pull
docker compose up -d --build
```

`.env` и `./data` при этом не трогаются. Останавливать всё: `docker compose down` (данные на диске остаются). `docker compose down -v` тома не удалит, потому что каталог примонтирован папкой, а не именованным томом — но саму папку `data` удалять нельзя.

HTTPS в образ не встроен. Если нужен адрес с сертификатом, перед портом 8088 ставят Caddy или nginx и проксируют на `127.0.0.1:8088`. В `docker-compose.yml` тогда публикуют порт только на localhost: `"127.0.0.1:8088:8000"`.

Приложение рассчитано на работу по обычному HTTP без домена.

## Вход

Сессия — cookie. `GET /api/auth/me` без сессии возвращает `null` и код 200, чтобы проверка входа не выглядела как сбой. Остальные закрытые маршруты отвечают 401.

```bat
curl -c cookies.txt -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"admin\"}" http://127.0.0.1:8000/api/auth/login
curl -b cookies.txt http://127.0.0.1:8000/api/auth/me
```

`GET http://127.0.0.1:8000/healthz` без входа отдаёт статус процесса, модули и имена джоб.
