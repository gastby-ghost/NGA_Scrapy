#!/bin/bash
# cleanup_images.sh — 清理服务器上的旧图片（2026-10-18）
#
# 图片已由本地每日增量同步；超过 KEEP_DAYS 天的图片删除，腾出服务器空间。
# 本地 rsync 不删除已有文件，因此删除后本地仍保留副本。
#
# 用法：KEEP_DAYS=30 bash scripts/cleanup_images.sh
# cron：每周日 04:00 运行（见部署记录）。

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
KEEP_DAYS="${KEEP_DAYS:-30}"

COUNT=$(find "$DIR/download_images" -type f -mtime +"$KEEP_DAYS" -delete -print 2>/dev/null | wc -l)
echo "[$(date '+%F %T')] 清理超过 ${KEEP_DAYS} 天的图片: ${COUNT} 个"
du -sh "$DIR/download_images" 2>/dev/null || true
df -h / | tail -1
