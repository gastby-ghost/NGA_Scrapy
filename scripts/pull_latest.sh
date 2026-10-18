#!/bin/bash
# pull_latest.sh — 拉取服务器数据到本地（2026-10-18）
#
# 默认（增量）：
#   bash scripts/pull_latest.sh              # 拉增量包并合并进本地主库 nga_scrapy
#   bash scripts/pull_latest.sh --fresh      # 先让服务器立刻导出增量，再拉取
#   bash scripts/pull_latest.sh --no-images  # 不同步图片
#
# 全量（对账/修复）：
#   bash scripts/pull_latest.sh --full       # 拉全量 dump 并恢复到 nga_scrapy_live
#
# 图片默认增量同步到项目内 download_images/（与库里 image_paths 对应）。
# 增量合并记录在 $DEST/incremental/.applied.json，只应用未处理过的包。

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${NGA_BACKUP_DIR:-$HOME/NGA_backups}"
HOST="${NGA_HOST:-aliyun-hust}"

FRESH=0
IMAGES=1
FULL=0
for arg in "$@"; do
    case "$arg" in
        --fresh) FRESH=1 ;;
        --no-images) IMAGES=0 ;;
        --full) FULL=1 ;;
    esac
done

if [ "$FRESH" = 1 ]; then
    echo "[$(date '+%F %T')] 触发服务器立即导出增量..."
    ssh "$HOST" 'cd /opt/nga_scrapy && ./venv/bin/python scripts/export_incremental.py'
fi

if [ "$IMAGES" = 1 ]; then
    SYNC_IMAGES=1 bash "$DIR/scripts/sync_from_server.sh" "$DEST"
else
    bash "$DIR/scripts/sync_from_server.sh" "$DEST"
fi

if [ "$FULL" = 1 ]; then
    LATEST="$(ls -t "$DEST"/nga_scrapy_*.dump | head -1)"
    echo "[$(date '+%F %T')] 全量恢复 $LATEST -> nga_scrapy_live"
    bash "$DIR/scripts/restore_local.sh" "$LATEST"
else
    "$DIR/venv/bin/python" "$DIR/scripts/merge_incremental.py" --auto "$DEST/incremental"
fi
