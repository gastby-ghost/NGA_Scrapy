#!/usr/bin/env python3
"""
移除 parent_rid 外键约束的数据库迁移脚本

支持 SQLite 和 PostgreSQL
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from database_config import get_database_url

def migrate_remove_parent_rid_fk():
    """移除 parent_rid 外键约束"""

    # 获取数据库 URL
    db_url = get_database_url()

    print(f"正在连接到数据库: {db_url}")

    engine = create_engine(db_url)

    with engine.connect() as conn:
        # 检查数据库类型
        if db_url.startswith('sqlite'):
            print("\n=== SQLite 数据库 ===")

            # SQLite 需要先禁用外键约束检查
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            conn.commit()

            # 删除外键约束（SQLite 不支持直接删除外键，需要重建表）
            # 这里我们采用更简单的方法：删除并重新创建表

            print("正在删除 reply 表中的外键约束...")

            # SQLite 的方法：重建表
            conn.execute(text("""
                CREATE TABLE reply_new (
                    rid TEXT PRIMARY KEY,
                    tid TEXT,
                    parent_rid TEXT,
                    content TEXT,
                    recommendvalue INTEGER,
                    poster_id TEXT,
                    post_time TEXT,
                    image_urls TEXT,
                    image_paths TEXT,
                    sampling_time TEXT,
                    FOREIGN KEY (tid) REFERENCES topic(tid),
                    FOREIGN KEY (poster_id) REFERENCES user(uid)
                )
            """))

            # 复制数据
            conn.execute(text("""
                INSERT INTO reply_new
                SELECT rid, tid, parent_rid, content, recommendvalue, poster_id,
                       post_time, image_urls, image_paths, sampling_time
                FROM reply
            """))

            # 删除旧表
            conn.execute(text("DROP TABLE reply"))

            # 重命名新表
            conn.execute(text("ALTER TABLE reply_new RENAME TO reply"))

            conn.commit()
            print("✓ SQLite: 已移除 parent_rid 外键约束")

            # 重新启用外键约束检查
            conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.commit()

        elif db_url.startswith('postgresql'):
            print("\n=== PostgreSQL 数据库 ===")

            # PostgreSQL: 删除外键约束
            print("正在删除外键约束...")
            try:
                conn.execute(text("""
                    ALTER TABLE reply DROP CONSTRAINT IF EXISTS reply_parent_rid_fkey
                """))
                conn.commit()
                print("✓ PostgreSQL: 已删除外键约束 reply_parent_rid_fkey")
            except Exception as e:
                print(f"警告: 可能不存在该约束或已删除: {e}")
                conn.rollback()

        else:
            print(f"警告: 未支持的数据库类型: {db_url.split('://')[0]}")
            return False

    print("\n✓ 迁移完成！")
    return True

if __name__ == "__main__":
    try:
        migrate_remove_parent_rid_fk()
    except Exception as e:
        print(f"\n✗ 迁移失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
