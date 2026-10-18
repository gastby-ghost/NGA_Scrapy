#!/bin/bash
# pull_latest.sh — 一键拉取服务器数据到本地独立库（2026-10-18）
#
# 用法：
#   bash scripts/pull_latest.sh            # 拉数据库备份 + 增量同步图片
#   bash scripts/pull_latest.sh --fresh    # 先让服务器立刻备份，再拉取（需要当天最新数据时用）
#   bash scripts/pull_latest.sh --no-images  # 只拉数据库，不同步图片
#
# 恢复到本地 nga_scrapy_live，不覆盖原有的 nga_scrapy 库。
# 图片增量同步到项目内 download_images/（与库里 image_paths 对应）。
# 结束后打印本地库的最新采样时间，作为"数据是否可用于执行"的判据。

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${NGA_BACKUP_DIR:-$HOME/NGA_backups}"
HOST="${NGA_HOST:-aliyun-hust}"

FRESH=0
IMAGES=1
for arg in "$@"; do
    case "$arg" in
        --fresh) FRESH=1 ;;
        --no-images) IMAGES=0 ;;
    esac
done

if [ "$FRESH" = 1 ]; then
    echo "[$(date '+%F %T')] 触发服务器立即备份..."
    ssh "$HOST" 'bash /opt/nga_scrapy/scripts/backup_db.sh'
fi

if [ "$IMAGES" = 1 ]; then
    SYNC_IMAGES=1 bash "$DIR/scripts/sync_from_server.sh" "$DEST"
else
    bash "$DIR/scripts/sync_from_server.sh" "$DEST"
fi

LATEST="$(ls -t "$DEST"/nga_scrapy_*.dump | head -1)"
echo "[$(date '+%F %T')] 恢复 $LATEST -> nga_scrapy_live"
bash "$DIR/scripts/restore_local.sh" "$LATEST"
