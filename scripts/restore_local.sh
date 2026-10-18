#!/bin/bash
# restore_local.sh — 把服务器备份恢复到本机独立库（2026-10-18）
#
# 用法：
#   bash scripts/restore_local.sh ~/NGA_backups/nga_scrapy_2026-10-18_0330.dump
#
# 恢复到 nga_scrapy_live（默认），不覆盖本地原有的 nga_scrapy 库。
# 本地 PostgreSQL 由 Docker 容器 nga-postgres 提供。

set -euo pipefail

DUMP="${1:?用法: bash scripts/restore_local.sh <dump 文件>}"
CONTAINER="${NGA_PG_CONTAINER:-nga-postgres}"
DB="${NGA_LIVE_DB:-nga_scrapy_live}"

[ -f "$DUMP" ] || { echo "找不到文件: $DUMP"; exit 1; }

# 建库（已存在则跳过）
if ! docker exec "$CONTAINER" psql -U nga -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
    docker exec "$CONTAINER" psql -U nga -d postgres -c "CREATE DATABASE \"$DB\" OWNER nga;"
fi

# 恢复（先清空库内已有对象，保证与备份一致）
docker exec -i "$CONTAINER" pg_restore -U nga -d "$DB" --clean --if-exists --no-owner < "$DUMP"

# 核对
docker exec "$CONTAINER" psql -U nga -d "$DB" -c \
    "SELECT (SELECT count(*) FROM topic) AS topics,
            (SELECT count(*) FROM reply) AS replies,
            (SELECT max(sampling_time) FROM reply) AS latest_sampling;"
