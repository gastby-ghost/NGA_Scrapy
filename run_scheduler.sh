#!/bin/bash
# run_scheduler.sh
# NGA爬虫调度器启动脚本（使用screen后台运行）
# 使用方法:
#   bash run_scheduler.sh              # 启动scheduler
#   bash run_scheduler.sh status       # 查看状态
#   bash run_scheduler.sh attach       # 连接到screen会话
#   bash run_scheduler.sh stop         # 停止scheduler
#   bash run_scheduler.sh restart      # 重启scheduler
#   bash run_scheduler.sh logs         # 查看日志

SCREEN_SESSION="nga_scheduler"
SCHEDULER_DIR="scheduler"
SCRIPT_NAME="run_scheduler.py"
LOG_FILE="${SCHEDULER_DIR}/scheduler.log"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "========================================="
echo "🚀 NGA爬虫调度器 - Screen后台运行模式"
echo "========================================="
echo ""

# 获取操作命令
COMMAND=${1:-"start"}

# 检查screen是否安装
check_screen() {
    if ! command -v screen &> /dev/null; then
        echo -e "${RED}❌ 未找到screen命令${NC}"
        echo "请安装screen:"
        echo "  Ubuntu/Debian: sudo apt-get install screen"
        echo "  CentOS/RHEL: sudo yum install screen"
        exit 1
    fi
}

# 检查虚拟环境
check_venv() {
    if [ ! -d "venv" ]; then
        echo -e "${RED}❌ 未找到虚拟环境${NC}"
        echo "请先运行:"
        echo "  python3 -m venv venv"
        echo "  source venv/bin/activate"
        echo "  pip install -r requirements.txt"
        exit 1
    fi
}

# 检查scheduler脚本
check_scheduler() {
    if [ ! -f "${SCHEDULER_DIR}/${SCRIPT_NAME}" ]; then
        echo -e "${RED}❌ 未找到调度器脚本: ${SCHEDULER_DIR}/${SCRIPT_NAME}${NC}"
        exit 1
    fi
}

# 检查邮件配置
check_email_config() {
    if [ ! -f "${SCHEDULER_DIR}/email_config.yaml" ]; then
        echo -e "${YELLOW}⚠️  未找到邮件配置文件: ${SCHEDULER_DIR}/email_config.yaml${NC}"
        echo -e "${YELLOW}   将跳过邮件通知功能${NC}"
        echo ""
        read -p "是否继续？(y/N): " continue_without_email
        if [ "$continue_without_email" != "y" ] && [ "$continue_without_email" != "Y" ]; then
            echo "请先配置邮件通知:"
            echo "  cp ${SCHEDULER_DIR}/email_config.yaml.example ${SCHEDULER_DIR}/email_config.yaml"
            echo "  编辑 ${SCHEDULER_DIR}/email_config.yaml 配置你的邮箱信息"
            exit 1
        fi
    else
        echo -e "${GREEN}✅ 邮件配置已存在${NC}"
    fi
}

# 检查数据库
check_database() {
    source venv/bin/activate
    python -c "
from database_config import get_database_url
try:
    from sqlalchemy import create_engine
    engine = create_engine(get_database_url())
    with engine.connect() as conn:
        pass
    print('database_ok')
except Exception as e:
    print(f'database_error: {e}')
"

    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ 数据库连接失败${NC}"
        echo "请检查数据库配置"
        exit 1
    fi
    echo -e "${GREEN}✅ 数据库连接正常${NC}"
}

# 启动scheduler
start_scheduler() {
    echo -e "${BLUE}📋 检查环境...${NC}"
    check_screen
    check_venv
    check_scheduler
    check_email_config
    check_database

    # 检查是否已在运行
    if screen -list | grep -q "${SCREEN_SESSION}"; then
        echo -e "${YELLOW}⚠️  scheduler已在运行${NC}"
        echo ""
        echo -e "${BLUE}使用以下命令管理:${NC}"
        echo "  查看状态: bash $0 status"
        echo "  重新连接: bash $0 attach"
        echo "  停止: bash $0 stop"
        echo "  查看日志: bash $0 logs"
        exit 0
    fi

    echo ""
    echo -e "${GREEN}🚀 启动调度器...${NC}"

    # 清空旧日志
    if [ -f "$LOG_FILE" ]; then
        > "$LOG_FILE"
        echo -e "${BLUE}📄 已清空旧日志${NC}"
    fi

    # 创建screen会话并启动scheduler
    screen -dmS "${SCREEN_SESSION}" bash -c "
        source venv/bin/activate
        cd '${SCHEDULER_DIR}'
        echo '========================================='
        echo '   NGA爬虫调度器已启动'
        echo '========================================='
        echo ''
        echo 'Screen会话名称: ${SCREEN_SESSION}'
        echo '日志文件: ${LOG_FILE}'
        echo ''
        echo '使用以下命令管理:'
        echo '  查看状态: bash $0 status'
        echo '  重新连接: bash $0 attach'
        echo '  停止: bash $0 stop'
        echo '  查看日志: bash $0 logs'
        echo ''
        echo '按 Ctrl+\\ 可以优雅退出'
        echo ''
        echo '========================================='
        echo ''
        python run_scheduler.py
    "

    # 等待1秒让screen启动
    sleep 1

    if screen -list | grep -q "${SCREEN_SESSION}"; then
        echo -e "${GREEN}✅ 调度器启动成功${NC}"
        echo ""
        echo -e "${BLUE}📊 状态信息:${NC}"
        echo "  Screen会话: ${SCREEN_SESSION}"
        echo "  日志文件: ${LOG_FILE}"
        echo ""
        echo -e "${BLUE}📋 管理命令:${NC}"
        echo "  查看状态: bash $0 status"
        echo "  重新连接: bash $0 attach"
        echo "  停止: bash $0 stop"
        echo "  查看日志: bash $0 logs"
        echo ""
        echo -e "${YELLOW}⏳ 等待10秒后查看初始日志...${NC}"
        sleep 10
        echo ""
        echo -e "${BLUE}📄 最近日志:${NC}"
        tail -n 20 "$LOG_FILE" 2>/dev/null || echo "日志文件尚未生成"
    else
        echo -e "${RED}❌ 调度器启动失败${NC}"
        echo "请检查日志文件: ${LOG_FILE}"
        exit 1
    fi
}

# 查看状态
status_scheduler() {
    if screen -list | grep -q "${SCREEN_SESSION}"; then
        echo -e "${GREEN}✅ 调度器正在运行${NC}"
        screen -list | grep "${SCREEN_SESSION}"

        # 显示日志文件大小
        if [ -f "$LOG_FILE" ]; then
            echo ""
            log_size=$(du -h "$LOG_FILE" | cut -f1)
            echo -e "${BLUE}📄 日志文件大小: ${log_size}${NC}"

            # 显示最近日志
            echo ""
            echo -e "${BLUE}📋 最近日志:${NC}"
            tail -n 10 "$LOG_FILE"
        fi

        # 检查stats目录
        stats_dir="${SCHEDULER_DIR}/stats"
        if [ -d "$stats_dir" ]; then
            echo ""
            echo -e "${BLUE}📊 统计文件:${NC}"
            ls -lh "$stats_dir"/*.json 2>/dev/null | tail -5
        fi
    else
        echo -e "${RED}❌ 调度器未运行${NC}"
    fi
}

# 重新连接到screen会话
attach_scheduler() {
    if screen -list | grep -q "${SCREEN_SESSION}"; then
        echo -e "${GREEN}📡 正在连接到调度器会话...${NC}"
        echo ""
        echo -e "${YELLOW}提示:${NC}"
        echo "  - 按 Ctrl+A 然后按 D 可以分离会话（保持运行）"
        echo "  - 按 Ctrl+\\ 可以优雅退出"
        echo ""
        sleep 2
        screen -r "${SCREEN_SESSION}"
    else
        echo -e "${RED}❌ 调度器未运行${NC}"
        echo "使用 'bash $0 start' 启动"
    fi
}

# 停止scheduler
stop_scheduler() {
    if screen -list | grep -q "${SCREEN_SESSION}"; then
        echo -e "${BLUE}⏹️  正在停止调度器...${NC}"

        # 发送终止信号给screen会话（Ctrl+\\）
        screen -S "${SCREEN_SESSION}" -X stuff '^\\'
        sleep 5

        # 如果还在运行，强制终止
        if screen -list | grep -q "${SCREEN_SESSION}"; then
            echo -e "${YELLOW}⚠️  强制终止session...${NC}"
            screen -S "${SCREEN_SESSION}" -X quit
            sleep 2
        fi

        if screen -list | grep -q "${SCREEN_SESSION}"; then
            echo -e "${RED}❌ 停止失败，请手动停止${NC}"
            echo "可以执行: screen -S ${SCREEN_SESSION} -X quit"
        else
            echo -e "${GREEN}✅ 调度器已停止${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  调度器未运行${NC}"
    fi
}

# 重启scheduler
restart_scheduler() {
    echo -e "${BLUE}🔄 正在重启调度器...${NC}"
    stop_scheduler
    sleep 3
    start_scheduler
}

# 查看日志
view_logs() {
    if [ -f "$LOG_FILE" ]; then
        echo -e "${BLUE}📄 查看日志 (实时更新):${NC}"
        echo "按 Ctrl+C 退出"
        echo ""
        tail -f "$LOG_FILE"
    else
        echo -e "${RED}❌ 日志文件不存在: ${LOG_FILE}${NC}"
        echo "可能原因:"
        echo "  1. 调度器尚未启动"
        echo "  2. 日志文件路径错误"
    fi
}

# 解析命令
case "$COMMAND" in
    start)
        start_scheduler
        ;;
    status)
        status_scheduler
        ;;
    attach)
        attach_scheduler
        ;;
    stop)
        stop_scheduler
        ;;
    restart)
        restart_scheduler
        ;;
    logs)
        view_logs
        ;;
    *)
        echo -e "${RED}❌ 未知命令: $COMMAND${NC}"
        echo ""
        echo -e "${BLUE}使用方法:${NC}"
        echo "  bash $0 start    - 启动调度器"
        echo "  bash $0 status   - 查看状态"
        echo "  bash $0 attach   - 连接到会话"
        echo "  bash $0 stop     - 停止调度器"
        echo "  bash $0 restart  - 重启调度器"
        echo "  bash $0 logs     - 查看日志"
        echo ""
        exit 1
        ;;
esac
