# init_db.py
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from NGA_Scrapy.models import Base
from database_config import get_database_url, get_engine_args
import os

def init_db():
    """初始化PostgreSQL数据库，创建所有表"""
    try:
        # 获取数据库连接URL
        database_url = get_database_url()

        # 获取引擎参数
        engine_args = get_engine_args()

        # 创建数据库引擎
        print("正在连接到 PostgreSQL 数据库...")
        engine = create_engine(database_url, **engine_args)

        # 测试连接
        with engine.connect() as conn:
            print("✅ 数据库连接成功")

        # 删除所有表（如果存在）
        print("正在删除旧表...")
        Base.metadata.drop_all(engine)

        # 创建所有表
        print("正在创建新表...")
        Base.metadata.create_all(engine)

        print("\n" + "=" * 60)
        print("✅ PostgreSQL数据库表重建成功！")
        print("=" * 60)
        print("数据表: user, topic, reply")
        print("连接池配置: 15 基础连接 + 30 溢出连接")
        print("=" * 60)

        print("\n💡 PostgreSQL优化建议:")
        print("  1. 可以同时处理多个并发请求")
        print("  2. 建议定期执行 VACUUM ANALYZE")
        print("  3. 考虑为常用字段添加索引")
        print("\n查看表结构:")
        print("  \\d user")
        print("  \\d topic")
        print("  \\d reply")

        return True

    except OperationalError as e:
        print("\n" + "=" * 60)
        print("❌ PostgreSQL数据库连接失败")
        print("=" * 60)
        print(f"错误信息: {str(e)}")

        print("\n🔧 解决方案:")
        print("1. 检查PostgreSQL服务是否运行:")
        print("   sudo systemctl status postgresql")
        print("\n2. 检查连接配置:")
        print(f"   主机: {os.getenv('POSTGRES_HOST', 'localhost')}")
        print(f"   端口: {os.getenv('POSTGRES_PORT', '5432')}")
        print(f"   用户: {os.getenv('POSTGRES_USER', 'postgres')}")
        print(f"   数据库: {os.getenv('POSTGRES_DB', 'nga_scrapy')}")
        print("\n3. 确认数据库存在:")
        print("   sudo -u postgres psql -l")
        print("\n4. 创建数据库（如果不存在）:")
        print("   sudo -u postgres createdb nga_scrapy")

        print("=" * 60 + "\n")
        return False

    except Exception as e:
        print(f"\n❌ 数据库操作失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def reset_db():
    """重置数据库（删除所有数据）"""
    print("\n⚠️  警告：这将删除所有现有数据！")
    response = input("确定要继续吗？(y/N): ")
    if response.lower() != 'y':
        print("操作已取消")
        return False

    return init_db()

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--reset':
        reset_db()
    else:
        init_db()
