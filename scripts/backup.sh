#!/usr/bin/env bash
# Nightly base backup (DEPLOYMENT.md §6). Custom format (-F c): compressed, supports
# parallel and selective restore, and is what restore.sh expects.
#
# Usage: scripts/backup.sh [output-dir]   (default: ./backups)
set -euo pipefail

OUT_DIR="${1:-backups}"
mkdir -p "$OUT_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$OUT_DIR/botbuilder-$STAMP.dump"

POSTGRES_USER="${POSTGRES_USER:-botbuilder}"
POSTGRES_DB="${POSTGRES_DB:-botbuilder}"

echo "Backing up $POSTGRES_DB -> $OUT_FILE"
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c > "$OUT_FILE"

SIZE=$(wc -c < "$OUT_FILE")
if [ "$SIZE" -lt 1024 ]; then
    echo "Refusing to call this a backup: $OUT_FILE is only $SIZE bytes." >&2
    exit 1
fi

echo "OK: $OUT_FILE ($SIZE bytes)"
