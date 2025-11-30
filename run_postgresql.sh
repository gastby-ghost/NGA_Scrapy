#!/bin/bash
# run_postgresql.sh
# PostgreSQL数据库专用启动脚本（针对2核4G服务器优化）
# 使用方法: bash run_postgresql.sh

echo "========================================="
echo "🚀 NGA爬虫 - PostgreSQL模式 (2核4G优化)"
echo "========================================="
echo ""

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 未找到虚拟环境，请先运行:"
    echo "   python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查环境变量文件
if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env 文件，请创建并配置PostgreSQL连接信息"
    echo ""
    echo "需要设置的关键参数:"
    echo "   POSTGRES_HOST=localhost"
    echo "   POSTGRES_USER=postgres"
    echo "   POSTGRES_PASSWORD=your_password"
    echo "   POSTGRES_DB=nga_scrapy"
    echo ""
    echo "示例 .env 文件内容:"
    cat << EOF
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=nga_scrapy
EOF
    echo ""
    echo "请创建 .env 文件后重新运行此脚本"
    exit 1
fi

# 检查PostgreSQL服务
echo ""
echo "🔍 检查PostgreSQL服务..."
if systemctl is-active --quiet postgresql; then
    echo "✅ PostgreSQL服务正在运行"
else
    echo "⚠️  PostgreSQL服务未运行"
    echo "启动命令: sudo systemctl start postgresql"
    echo ""
    read -p "是否现在启动PostgreSQL？(y/N): " start_pg
    if [ "$start_pg" = "y" ] || [ "$start_pg" = "Y" ]; then
        sudo systemctl start postgresql
        if [ $? -eq 0 ]; then
            echo "✅ PostgreSQL已启动"
        else
            echo "❌ PostgreSQL启动失败"
            exit 1
        fi
    else
        echo "请先启动PostgreSQL服务"
        exit 1
    fi
fi

# 检查数据库连接
echo ""
echo "🗄️  检查数据库连接..."
python -c "
from database_config import get_database_url
from sqlalchemy import create_engine
import sys

try:
    engine = create_engine(get_database_url())
    with engine.connect() as conn:
        print('✅ PostgreSQL连接成功')
except Exception as e:
    print(f'❌ PostgreSQL连接失败: {e}')
    print('')
    print('请检查:')
    print('1. .env 文件中的配置是否正确')
    print('2. PostgreSQL服务是否运行')
    print('3. 数据库和用户是否存在')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    exit 1
fi

# 检查表是否存在
echo ""
echo "📊 检查数据表..."
python -c "
from sqlalchemy import text
from database_config import get_database_url, get_engine_args
from sqlalchemy import create_engine

engine = create_engine(get_database_url(), **get_engine_args())

with engine.connect() as conn:
    # 检查表是否存在
    result = conn.execute(text(\"SELECT table_name FROM information_schema.tables WHERE table_schema='public'\"))
    tables = [row[0] for row in result.fetchall()]

    required_tables = ['user', 'topic', 'reply']
    existing_tables = [t for t in required_tables if t in tables]

    if len(existing_tables) == len(required_tables):
        print(f'✅ 所有数据表已存在 ({len(existing_tables)}/{len(required_tables)})')

        # 显示数据量
        for table in required_tables:
            result = conn.execute(text(f'SELECT COUNT(*) FROM {table}'))
            count = result.scalar()
            print(f'   {table}: {count} 条记录')
    else:
        print(f'⚠️  数据表不完整 ({len(existing_tables)}/{len(required_tables)})')
        print('需要初始化数据库')
        import sys
        sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo ""
    read -p "是否初始化数据库？(这将创建数据表)(y/N): " init_db
    if [ "$init_db" = "y" ] || [ "$init_db" = "Y" ]; then
        echo ""
        echo "正在初始化数据库..."
        python init_db.py
        if [ $? -ne 0 ]; then
            echo "❌ 数据库初始化失败"
            exit 1
        fi
    else
        echo "请先初始化数据库: python init_db.py"
        exit 1
    fi
fi

# 显示数据库配置
echo ""
echo "📊 当前数据库配置:"
python -c "
from database_config import print_config
print_config()
"

echo ""
echo "========================================="
echo "🎯 启动参数 (2核4G服务器优化):"
echo "  数据库: PostgreSQL"
echo "  连接池: 15 基础 + 30 溢出"
echo "  浏览器池: 3 (内存优化)"
echo "  并发请求: 3 (性能提升)"
echo "  下载延迟: 1-2秒"
echo "  超时时间: 20秒"
echo "========================================="
echo ""

# 启动爬虫
echo "🚀 启动爬虫..."
echo "日志文件: nga_spider.log"
echo "按 Ctrl+C 停止"
echo ""

scrapy crawl nga -s SETTINGS_MODULE=settings_cloud

echo ""
echo "========================================="
echo "✅ 爬虫已停止"
echo "========================================="
