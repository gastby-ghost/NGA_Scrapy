#!/bin/bash
# run_scheduler_local.sh — 本地后台运行调度器（nohup 版；本机未装 screen，替代 run_scheduler.sh）
# 用法:
#   bash run_scheduler_local.sh start     # 启动（后台，日志 scheduler/scheduler.log）
#   bash run_scheduler_local.sh stop      # 优雅停止（SIGTERM，调度器自会收尾）
#   bash run_scheduler_local.sh status    # 状态
#   bash run_scheduler_local.sh logs      # 跟踪日志
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/scheduler/scheduler.pid"
LOGFILE="$DIR/scheduler/scheduler.log"

case "${1:-status}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "调度器已在运行（PID $(cat "$PIDFILE")）"; exit 0
    fi
    cd "$DIR/scheduler" || exit 1
    # shellcheck disable=SC1091
    source "$DIR/venv/bin/activate"
    { echo ""; echo "===== 启动 $(date '+%F %T') ====="; } >> "$LOGFILE"
    # stdout/stderr 单独落盘：捕获 logging 初始化前的早期崩溃输出（正常运行时为空）
    nohup python run_scheduler.py </dev/null >> "$DIR/scheduler/scheduler.stdout.log" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 3
    if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "✅ 调度器已启动（PID $(cat "$PIDFILE")）"
      echo "   日志: $LOGFILE"
      echo "   首轮爬虫在启动后立即执行，之后每 30 分钟一轮"
    else
      echo "❌ 启动失败，见日志：$LOGFILE"; exit 1
    fi
    ;;
  stop)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      PID="$(cat "$PIDFILE")"
      kill -TERM "$PID" && echo "已发送 SIGTERM（PID $PID），等待优雅退出…"
      for _ in $(seq 1 20); do
        kill -0 "$PID" 2>/dev/null || { echo "✅ 已停止"; rm -f "$PIDFILE"; exit 0; }
        sleep 1
      done
      echo "⚠️ 20 秒未退出（PID $PID 仍在），请检查日志"; exit 1
    else
      echo "调度器未在运行"; rm -f "$PIDFILE"
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "✅ 运行中（PID $(cat "$PIDFILE")）"
      ps -o pid,etime,rss,cmd -p "$(cat "$PIDFILE")" --no-headers
      [ -f "$LOGFILE" ] && echo "日志大小: $(du -h "$LOGFILE" | cut -f1)"
    else
      echo "❌ 未运行"
    fi
    ;;
  logs)
    tail -f "$LOGFILE"
    ;;
  *)
    echo "用法: bash $0 {start|stop|status|logs}"; exit 1
    ;;
esac
