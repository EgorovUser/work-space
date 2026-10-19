#!/usr/bin/env bash
# Консистентный бэкап: SQLite (.backup), data/files и .env
# Использование: ./scripts/backup.sh
# Переменные: BACKUP_KEEP (сколько хранить архивов, по умолчанию 7)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$ROOT/data}"
DB="$DATA_DIR/app.db"
FILES_DIR="$DATA_DIR/files"
ENV_FILE="$ROOT/.env"
BACKUP_DIR="$DATA_DIR/backups"
KEEP="${BACKUP_KEEP:-7}"
STAMP="$(date +%Y%m%d-%H%M)"
TMP_DB="$(mktemp -u "/tmp/work-space-db-XXXXXX.db")"
ARCHIVE="$BACKUP_DIR/work-space-$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

if [[ ! -f "$DB" ]]; then
  echo "База не найдена: $DB" >&2
  exit 1
fi

echo "Делаю консистентную копию базы..."
sqlite3 "$DB" ".backup '$TMP_DB'"

# Проверяем целостность копии
if ! sqlite3 "$TMP_DB" "PRAGMA integrity_check;" | grep -q "^ok$"; then
  echo "Копия базы не прошла integrity_check" >&2
  rm -f "$TMP_DB"
  exit 1
fi

echo "Упаковываю архив..."
(
  cd "$ROOT"
  tar -czf "$ARCHIVE" \
    --transform "s|^$TMP_DB|data/app.db|" \
    "$TMP_DB" \
    "${FILES_DIR#$ROOT/}" \
    ".env" 2>/dev/null || true
)

rm -f "$TMP_DB"

# Храним только последние N архивов
ls -1t "$BACKUP_DIR"/work-space-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "Готово: $ARCHIVE"
echo "Проверка: tar -tzf \"$ARCHIVE\" | head"
