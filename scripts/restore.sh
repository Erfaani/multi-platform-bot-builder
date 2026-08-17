#!/usr/bin/env bash
# Restore drill (DEPLOYMENT.md §6 — "an untested backup is not a backup"). Restores into
# a *separate* target database by default, never over the live one, so this is safe to
# run against a production dump without any risk of clobbering the running database —
# restoring over the live database in a real incident is a deliberate, separate step
# (`--target-is-live`), not this script's default behaviour.
#
# Usage: scripts/restore.sh <dump-file> [target-db]   (default target: botbuilder_restore_drill)
set -euo pipefail

DUMP_FILE="${1:?Usage: scripts/restore.sh <dump-file> [target-db]}"
TARGET_DB="${2:-botbuilder_restore_drill}"
POSTGRES_USER="${POSTGRES_USER:-botbuilder}"

if [ ! -f "$DUMP_FILE" ]; then
    echo "No such dump file: $DUMP_FILE" >&2
    exit 1
fi

echo "Recreating $TARGET_DB"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS $TARGET_DB;" \
    -c "CREATE DATABASE $TARGET_DB OWNER $POSTGRES_USER;"

echo "Restoring $DUMP_FILE -> $TARGET_DB"
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$TARGET_DB" --no-owner --exit-on-error < "$DUMP_FILE"

echo "OK: restored into $TARGET_DB"
