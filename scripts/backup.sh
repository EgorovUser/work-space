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
TMP_DIR="$(mktemp -d)"
ARCHIVE="$BACKUP_DIR/work-space-$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

if [[ ! -f "$DB" ]]; then
  echo "База не найдена: $DB" >&2
  exit 1
fi

echo "Делаю консистентную копию базы..."
sqlite3 "$DB" ".backup '$TMP_DIR/app.db'"

if ! sqlite3 "$TMP_DIR/app.db" "PRAGMA integrity_check;" | grep -q "^ok$"; then
  echo "Копия базы не прошла integrity_check" >&2
  exit 1
fi

mkdir -p "$TMP_DIR/data"
mv "$TMP_DIR/app.db" "$TMP_DIR/data/app.db"
if [[ -d "$FILES_DIR" ]]; then
  cp -a "$FILES_DIR" "$TMP_DIR/data/files"
fi
if [[ -f "$ENV_FILE" ]]; then
  cp "$ENV_FILE" "$TMP_DIR/.env"
fi

echo "Упаковываю архив..."
tar -czf "$ARCHIVE" -C "$TMP_DIR" .

# Храним только последние N архивов
ls -1t "$BACKUP_DIR"/work-space-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "Готово: $ARCHIVE"
echo "Проверка: tar -tzf \"$ARCHIVE\" | head"
