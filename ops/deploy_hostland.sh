#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

readonly DEPLOY_SHA="${1:-}"
readonly SOURCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly SOURCE_APP="$SOURCE_ROOT/skinali"
readonly APP_DIR="/home/host1889656/odium.by/projects/odium"
readonly PYTHON_BIN="/home/host1889656/odium.by/venv/python_3.11/bin/python"
readonly BACKUP_ROOT="/home/host1889656/odium.by/backups/automatic-deploy"
readonly BACKUPS_TO_KEEP=5

backup_dir=""
code_changed=false

fail() {
    echo "Ошибка деплоя: $*" >&2
    exit 1
}

validate_paths() {
    [[ "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "некорректный commit SHA"
    [[ "$SOURCE_ROOT" == "/home/host1889656/odium.by/repositories/dushnila" ]] \
        || fail "неожиданный каталог исходников: $SOURCE_ROOT"
    [[ "$APP_DIR" == "/home/host1889656/odium.by/projects/odium" ]] \
        || fail "неожиданный каталог приложения: $APP_DIR"
    [[ -x "$PYTHON_BIN" ]] || fail "Python не найден: $PYTHON_BIN"
    [[ -f "$APP_DIR/.env" ]] || fail "production .env не найден"
    [[ -f "$APP_DIR/db.sqlite3" ]] || fail "production db.sqlite3 не найден"
    [[ -f "$SOURCE_ROOT/requirements-production.txt" ]] \
        || fail "requirements-production.txt не найден"
    [[ -f "$SOURCE_APP/manage.py" ]] || fail "manage.py не найден в исходниках"

    local directory
    for directory in pict sitecontent skinali; do
        [[ -d "$SOURCE_APP/$directory" ]] \
            || fail "нет каталога исходников $SOURCE_APP/$directory"
        [[ -d "$APP_DIR/$directory" ]] \
            || fail "нет production-каталога $APP_DIR/$directory"
    done
}

create_backup() {
    local timestamp
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    backup_dir="$BACKUP_ROOT/${timestamp}-${DEPLOY_SHA:0:12}"
    mkdir -p "$backup_dir/code"

    "$PYTHON_BIN" - "$APP_DIR/db.sqlite3" "$backup_dir/db.sqlite3" <<'PYTHON'
import sqlite3
import sys

source_path, target_path = sys.argv[1:]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(target_path)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PYTHON

    local directory
    for directory in pict sitecontent skinali; do
        rsync -a "$APP_DIR/$directory/" "$backup_dir/code/$directory/"
    done
    cp -p "$APP_DIR/manage.py" "$backup_dir/code/manage.py"
    cp -p "$APP_DIR/requirements-production.txt" \
        "$backup_dir/code/requirements-production.txt"
    printf '%s\n' "$DEPLOY_SHA" > "$backup_dir/deploy-sha.txt"
}

restore_code_after_error() {
    local exit_code=$?
    trap - ERR

    if [[ "$code_changed" == true && -n "$backup_dir" && -d "$backup_dir/code" ]]; then
        echo "Деплой завершился ошибкой. Восстанавливается предыдущая версия кода." >&2

        local directory
        for directory in pict sitecontent skinali; do
            rsync -a --delete "$backup_dir/code/$directory/" "$APP_DIR/$directory/"
        done
        cp -p "$backup_dir/code/manage.py" "$APP_DIR/manage.py"
        cp -p "$backup_dir/code/requirements-production.txt" \
            "$APP_DIR/requirements-production.txt"

        "$PYTHON_BIN" "$APP_DIR/manage.py" collectstatic --noinput || true
        touch "$APP_DIR/tmp/restart.txt"
    fi

    echo "Резервная копия базы сохранена в $backup_dir/db.sqlite3" >&2
    exit "$exit_code"
}

sync_code() {
    local directory
    for directory in pict sitecontent skinali; do
        rsync -a --delete \
            --exclude '__pycache__/' \
            --exclude '*.py[co]' \
            "$SOURCE_APP/$directory/" "$APP_DIR/$directory/"
    done

    install -m 0644 "$SOURCE_APP/manage.py" "$APP_DIR/manage.py"
    install -m 0644 "$SOURCE_ROOT/requirements-production.txt" \
        "$APP_DIR/requirements-production.txt"
    code_changed=true
}

cleanup_old_backups() {
    local -a backups=()
    mapfile -t backups < <(
        find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
            -name '????????T??????Z-*' -printf '%T@ %p\n' \
            | sort -nr \
            | cut -d' ' -f2-
    )

    local backup
    for backup in "${backups[@]:$BACKUPS_TO_KEEP}"; do
        case "$backup" in
            "$BACKUP_ROOT"/*) rm -rf -- "$backup" ;;
            *) fail "отказано в удалении неожиданного пути backup: $backup" ;;
        esac
    done
}

validate_paths
mkdir -p "$BACKUP_ROOT"
create_backup
trap restore_code_after_error ERR

sync_code

"$PYTHON_BIN" -m pip install --disable-pip-version-check \
    -r "$APP_DIR/requirements-production.txt"
"$PYTHON_BIN" "$APP_DIR/manage.py" check
"$PYTHON_BIN" "$APP_DIR/manage.py" check --deploy
"$PYTHON_BIN" "$APP_DIR/manage.py" collectstatic --noinput
"$PYTHON_BIN" "$APP_DIR/manage.py" migrate --noinput
touch "$APP_DIR/tmp/restart.txt"

trap - ERR
cleanup_old_backups

echo "Деплой $DEPLOY_SHA успешно завершён."
echo "Резервная копия: $backup_dir"
