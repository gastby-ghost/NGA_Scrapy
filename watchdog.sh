#!/bin/bash
# watchdog.sh — 调度器保活（crontab 每 5 分钟调用，2026-10-14）
# 逻辑：PID 文件不存在或进程已死 → 自动重新拉起调度器。
# 覆盖场景：调度器意外崩溃、WSL/systemd 重启后无人值守恢复（cron 服务 enable，随 WSL 启动）。
# 注意：Windows 关机期间 WSL 整体不在运行——开机后需有一次 WSL 活动（打开终端即触发）。
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/scheduler/scheduler.pid"
LOG="$DIR/scheduler/watchdog.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0  # 调度器活着，什么都不做
fi

echo "[$(date '+%F %T')] 调度器未运行，自动拉起" >> "$LOG"
bash "$DIR/run_scheduler_local.sh" start >> "$LOG" 2>&1
