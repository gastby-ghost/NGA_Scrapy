#!/bin/bash
# backup_db.sh — 服务器端每日数据库备份（2026-10-18）
# 由 crontab 每日 03:30 调用；也可手动执行。
# 输出：backups/nga_scrapy_YYYY-MM-DD_HHMM.dump（自定义压缩格式），保留最近 14 份。

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$DIR/backups"
mkdir -p "$BACKUP_DIR"

cd "$DIR"
# shellcheck disable=SC1091
set -a; source .env; set +a

STAMP="$(date +%F_%H%M)"
OUT="$BACKUP_DIR/nga_scrapy_${STAMP}.dump"

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --no-owner --no-privileges -Fc -f "$OUT"

echo "[$(date '+%F %T')] 备份完成: $OUT ($(du -h "$OUT" | cut -f1))"

# 只保留最近 14 份
ls -1t "$BACKUP_DIR"/nga_scrapy_*.dump 2>/dev/null | tail -n +15 | xargs -r rm -f
