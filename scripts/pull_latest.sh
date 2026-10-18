#!/bin/bash
# pull_latest.sh — 一键拉取服务器数据到本地独立库（2026-10-18）
#
# 用法：
#   bash scripts/pull_latest.sh            # 拉取服务器最近一次备份（每日 03:30 自动生成）
#   bash scripts/pull_latest.sh --fresh    # 先让服务器立刻备份，再拉取（需要当天最新数据时用）
#
# 恢复到本地 nga_scrapy_live，不覆盖原有的 nga_scrapy 库。
# 结束后打印本地库的最新采样时间，作为"数据是否可用于执行"的判据。

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${NGA_BACKUP_DIR:-$HOME/NGA_backups}"
HOST="${NGA_HOST:-aliyun-hust}"

if [ "${1:-}" = "--fresh" ]; then
    echo "[$(date '+%F %T')] 触发服务器立即备份..."
    ssh "$HOST" 'bash /opt/nga_scrapy/scripts/backup_db.sh'
fi

bash "$DIR/scripts/sync_from_server.sh" "$DEST"

LATEST="$(ls -t "$DEST"/nga_scrapy_*.dump | head -1)"
echo "[$(date '+%F %T')] 恢复 $LATEST -> nga_scrapy_live"
bash "$DIR/scripts/restore_local.sh" "$LATEST"
