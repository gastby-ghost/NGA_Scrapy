# init_db.py
from sqlalchemy import create_engine
from NGA_Scrapy.models import Base

# 数据库连接配置
DATABASE_URL = "sqlite:///nga.db"  # 使用SQLite数据库

# 创建数据库引擎
engine = create_engine(DATABASE_URL)

# 创建所有表
def init_db():
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        print("数据库表重建成功")
    except Exception as e:
        print(f"数据库操作失败: {e}")

if __name__ == "__main__":
    init_db()
