#!/bin/bash
# sync_from_server.sh — 把服务器上的数据库备份拉到本机（2026-10-18）
#
# 用法：
#   bash scripts/sync_from_server.sh                 # 拉取到 ~/NGA_backups
#   bash scripts/sync_from_server.sh /path/to/dest   # 指定目录
#   SYNC_IMAGES=1 bash scripts/sync_from_server.sh   # 同时增量同步图片目录
#
# 前置：本机 ~/.ssh/config 已配置 aliyun-hust（见部署记录）。
# 只增量传输，不删除本地已有的历史备份。

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HOME/NGA_backups}"
HOST="${NGA_HOST:-aliyun-hust}"
REMOTE_DIR="/opt/nga_scrapy"

mkdir -p "$DEST"

echo "[$(date '+%F %T')] 同步数据库备份 -> $DEST"
rsync -az --info=stats1 "$HOST:$REMOTE_DIR/backups/" "$DEST/"

if [ "${SYNC_IMAGES:-0}" = "1" ]; then
    echo "[$(date '+%F %T')] 增量同步图片 -> $DIR/download_images（只传新增/变化的文件）"
    mkdir -p "$DIR/download_images"
    rsync -az --info=stats1 "$HOST:$REMOTE_DIR/download_images/" "$DIR/download_images/"
fi

echo "最近备份："
ls -lt "$DEST" | head -4
