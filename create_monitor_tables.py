# create_monitor_tables.py
"""只创建缺失的新表（post / monitor_thread），绝不触碰既有数据表。

（不要用 init_db.py —— 它会 drop_all 重建全部表。）
"""
from sqlalchemy import create_engine, inspect

from NGA_Scrapy.models import Base
from database_config import get_database_url, get_engine_args


def main():
    engine = create_engine(get_database_url(), **get_engine_args())
    before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(engine)  # checkfirst 默认 True：只建缺失的表
    after = set(inspect(engine).get_table_names())
    print("新建表:", sorted(after - before) or "（无，均已存在）")
    print("现有表:", sorted(after))
    engine.dispose()


if __name__ == "__main__":
    main()
