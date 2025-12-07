#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库分区管理模块

提供PostgreSQL分区表支持，通过按时间分区优化大数据量查询性能。

主要功能:
1. 自动创建时间分区表
2. 分区管理和维护
3. 分区查询优化
4. 数据归档和清理
5. 分区性能监控

作者: Claude Code
日期: 2025-12-07
"""

import time
import logging
from datetime import datetime, timedelta
from sqlalchemy import text, inspect
from sqlalchemy.exc import SQLAlchemyError


class PartitionManager:
    """分区管理器"""

    def __init__(self, db_session, logger=None):
        """初始化分区管理器

        Args:
            db_session: SQLAlchemy会话
            logger: 日志记录器
        """
        self.db_session = db_session
        self.logger = logger or logging.getLogger(__name__)

    def create_partitioned_table(self, table_name, partition_column, partition_type='range'):
        """创建分区表

        Args:
            table_name: 表名
            partition_column: 分区列名
            partition_type: 分区类型（'range' 或 'list'）

        Returns:
            bool: 是否创建成功
        """
        try:
            # 检查表是否已存在
            inspector = inspect(self.db_session.bind)
            if table_name in inspector.get_table_names():
                self.logger.info(f"表 {table_name} 已存在，跳过创建")
                return True

            if partition_type == 'range':
                # 创建基于时间范围的分区表
                sql = f"""
                CREATE TABLE {table_name} (
                    LIKE {table_name}_template INCLUDING ALL
                ) PARTITION BY RANGE ({partition_column});
                """
            else:
                # 创建基于列表的分区表
                sql = f"""
                CREATE TABLE {table_name} (
                    LIKE {table_name}_template INCLUDING ALL
                ) PARTITION BY LIST ({partition_column});
                """

            self.logger.info(f"正在创建分区表: {table_name}")
            self.db_session.execute(text(sql))
            self.db_session.commit()

            self.logger.info(f"分区表 {table_name} 创建成功")
            return True

        except SQLAlchemyError as e:
            self.logger.error(f"创建分区表失败: {e}")
            self.db_session.rollback()
            return False
        except Exception as e:
            self.logger.error(f"创建分区表发生意外错误: {e}")
            self.db_session.rollback()
            return False

    def create_monthly_partition(self, table_name, year, month):
        """创建月度分区

        Args:
            table_name: 表名
            year: 年份
            month: 月份

        Returns:
            str: 分区名
        """
        try:
            partition_name = f"{table_name}_p{year}{month:02d}"

            # 检查分区是否已存在
            inspector = inspect(self.db_session.bind)
            existing_tables = inspector.get_table_names()
            if partition_name in existing_tables:
                self.logger.debug(f"分区 {partition_name} 已存在")
                return partition_name

            # 获取月份范围
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)

            # 创建分区SQL
            sql = f"""
            CREATE TABLE {partition_name}
            PARTITION OF {table_name}
            FOR VALUES FROM ('{start_date.strftime("%Y-%m-%d")}') TO ('{end_date.strftime("%Y-%m-%d")}');
            """

            self.logger.info(f"正在创建月度分区: {partition_name} ({start_date.date()} - {end_date.date()})")
            self.db_session.execute(text(sql))
            self.db_session.commit()

            self.logger.info(f"分区 {partition_name} 创建成功")
            return partition_name

        except SQLAlchemyError as e:
            self.logger.error(f"创建月度分区失败: {e}")
            self.db_session.rollback()
            return None
        except Exception as e:
            self.logger.error(f"创建月度分区发生意外错误: {e}")
            self.db_session.rollback()
            return None

    def create_partitions_for_range(self, table_name, start_year, start_month, end_year, end_month):
        """批量创建时间范围分区

        Args:
            table_name: 表名
            start_year: 起始年份
            start_month: 起始月份
            end_year: 结束年份
            end_month: 结束月份

        Returns:
            list: 创建的分区名列表
        """
        created_partitions = []
        current_year = start_year
        current_month = start_month

        while current_year < end_year or (current_year == end_year and current_month <= end_month):
            partition_name = self.create_monthly_partition(table_name, current_year, current_month)
            if partition_name:
                created_partitions.append(partition_name)

            # 移动到下一个月
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1

        self.logger.info(f"批量创建分区完成，共 {len(created_partitions)} 个分区")
        return created_partitions

    def auto_create_partitions(self, table_name, months_ahead=3):
        """自动创建未来几个月的分区

        Args:
            table_name: 表名
            months_ahead: 向前创建的月数

        Returns:
            list: 创建的分区名列表
        """
        created_partitions = []
        now = datetime.now()

        for i in range(months_ahead):
            # 计算目标月份
            target_date = now + timedelta(days=30 * i)
            year = target_date.year
            month = target_date.month

            partition_name = self.create_monthly_partition(table_name, year, month)
            if partition_name:
                created_partitions.append(partition_name)

        self.logger.info(f"自动创建分区完成，共 {len(created_partitions)} 个分区")
        return created_partitions

    def get_partition_info(self, table_name):
        """获取分区信息

        Args:
            table_name: 表名

        Returns:
            list: 分区信息列表
        """
        try:
            sql = f"""
            SELECT
                schemaname,
                tablename,
                tableowner,
                hasindexes,
                hasrules,
                hastriggers
            FROM pg_tables
            WHERE tablename LIKE '{table_name}_p%'
            ORDER BY tablename;
            """

            result = self.db_session.execute(text(sql))
            partitions = []
            for row in result:
                partitions.append({
                    'schema': row[0],
                    'table': row[1],
                    'owner': row[2],
                    'has_indexes': row[3],
                    'has_rules': row[4],
                    'has_triggers': row[5]
                })

            self.logger.info(f"表 {table_name} 共有 {len(partitions)} 个分区")
            return partitions

        except SQLAlchemyError as e:
            self.logger.error(f"获取分区信息失败: {e}")
            return []
        except Exception as e:
            self.logger.error(f"获取分区信息发生意外错误: {e}")
            return []

    def get_partition_stats(self, table_name):
        """获取分区统计信息

        Args:
            table_name: 表名

        Returns:
            list: 分区统计信息
        """
        try:
            sql = f"""
            SELECT
                schemaname,
                tablename,
                n_tup_ins as inserts,
                n_tup_upd as updates,
                n_tup_del as deletes,
                n_live_tup as live_tuples,
                n_dead_tup as dead_tuples,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze
            FROM pg_stat_user_tables
            WHERE tablename LIKE '{table_name}_p%'
            ORDER BY tablename;
            """

            result = self.db_session.execute(text(sql))
            stats = []
            for row in result:
                stats.append({
                    'schema': row[0],
                    'table': row[1],
                    'inserts': row[2],
                    'updates': row[3],
                    'deletes': row[4],
                    'live_tuples': row[5],
                    'dead_tuples': row[6],
                    'last_vacuum': row[7],
                    'last_autovacuum': row[8],
                    'last_analyze': row[9],
                    'last_autoanalyze': row[10]
                })

            return stats

        except SQLAlchemyError as e:
            self.logger.error(f"获取分区统计失败: {e}")
            return []
        except Exception as e:
            self.logger.error(f"获取分区统计发生意外错误: {e}")
            return []

    def drop_partition(self, partition_name, cascade=False):
        """删除分区

        Args:
            partition_name: 分区名
            cascade: 是否级联删除

        Returns:
            bool: 是否删除成功
        """
        try:
            cascade_sql = " CASCADE" if cascade else ""
            sql = f"DROP TABLE {partition_name}{cascade_sql};"

            self.logger.warning(f"正在删除分区: {partition_name}")
            self.db_session.execute(text(sql))
            self.db_session.commit()

            self.logger.info(f"分区 {partition_name} 删除成功")
            return True

        except SQLAlchemyError as e:
            self.logger.error(f"删除分区失败: {e}")
            self.db_session.rollback()
            return False
        except Exception as e:
            self.logger.error(f"删除分区发生意外错误: {e}")
            self.db_session.rollback()
            return False

    def detach_partition(self, partition_name):
        """分离分区（将分区转为独立表）

        Args:
            partition_name: 分区名

        Returns:
            bool: 是否分离成功
        """
        try:
            sql = f"ALTER TABLE {partition_name} NO INHERIT;"

            self.logger.info(f"正在分离分区: {partition_name}")
            self.db_session.execute(text(sql))
            self.db_session.commit()

            self.logger.info(f"分区 {partition_name} 分离成功")
            return True

        except SQLAlchemyError as e:
            self.logger.error(f"分离分区失败: {e}")
            self.db_session.rollback()
            return False
        except Exception as e:
            self.logger.error(f"分离分区发生意外错误: {e}")
            self.db_session.rollback()
            return False

    def vacuum_partition(self, partition_name):
        """清理分区

        Args:
            partition_name: 分区名

        Returns:
            bool: 是否清理成功
        """
        try:
            sql = f"VACUUM ANALYZE {partition_name};"

            self.logger.info(f"正在清理分区: {partition_name}")
            start_time = time.time()
            self.db_session.execute(text(sql))
            self.db_session.commit()
            elapsed = time.time() - start_time

            self.logger.info(f"分区 {partition_name} 清理完成，耗时 {elapsed:.3f}s")
            return True

        except SQLAlchemyError as e:
            self.logger.error(f"清理分区失败: {e}")
            self.db_session.rollback()
            return False
        except Exception as e:
            self.logger.error(f"清理分区发生意外错误: {e}")
            self.db_session.rollback()
            return False

    def cleanup_old_partitions(self, table_name, keep_months=12):
        """清理旧分区

        Args:
            table_name: 表名
            keep_months: 保留月数

        Returns:
            int: 删除的分区数
        """
        try:
            # 计算截止时间
            cutoff_date = datetime.now() - timedelta(days=30 * keep_months)
            cutoff_str = cutoff_date.strftime("%Y%m")

            # 获取所有分区
            partitions = self.get_partition_info(table_name)
            deleted_count = 0

            for partition in partitions:
                partition_name = partition['table']
                # 提取分区名中的日期
                if '_p' in partition_name:
                    date_part = partition_name.split('_p')[-1]
                    if date_part < cutoff_str:
                        # 分区已过期，删除
                        self.drop_partition(partition_name)
                        deleted_count += 1

            self.logger.info(f"清理旧分区完成，删除 {deleted_count} 个分区")
            return deleted_count

        except Exception as e:
            self.logger.error(f"清理旧分区失败: {e}")
            return 0

    def optimize_partition_queries(self, table_name, time_column):
        """优化分区查询

        Args:
            table_name: 表名
            time_column: 时间列名

        Returns:
            dict: 优化建议
        """
        suggestions = {
            'indexes': [],
            'queries': [],
            'statistics': []
        }

        try:
            # 检查分区索引
            partitions = self.get_partition_info(table_name)
            if not partitions:
                suggestions['statistics'].append("未找到分区，建议先创建分区")
                return suggestions

            # 建议为每个分区创建索引
            for partition in partitions:
                partition_name = partition['table']
                suggestions['indexes'].append(
                    f"CREATE INDEX ON {partition_name} ({time_column});"
                )

            # 建议使用分区裁剪的查询方式
            suggestions['queries'].append(
                f"SELECT * FROM {table_name} WHERE {time_column} >= '2025-01-01' AND {time_column} < '2025-02-01';"
            )

            # 统计信息
            stats = self.get_partition_stats(table_name)
            suggestions['statistics'].append(f"共 {len(partitions)} 个分区")
            suggestions['statistics'].append(f"总记录数: {sum(s['live_tuples'] for s in stats)}")
            suggestions['statistics'].append(f"总死元组数: {sum(s['dead_tuples'] for s in stats)}")

            return suggestions

        except Exception as e:
            self.logger.error(f"分区查询优化失败: {e}")
            return suggestions


# 便捷函数
def create_partition_manager(db_session, logger=None):
    """创建分区管理器实例"""
    return PartitionManager(db_session, logger)


def auto_setup_partitions(db_session, table_name, months_ahead=3, keep_months=12, logger=None):
    """便捷函数：自动设置分区

    Args:
        db_session: SQLAlchemy会话
        table_name: 表名
        months_ahead: 向前创建的月数
        keep_months: 保留月数
        logger: 日志记录器

    Returns:
        bool: 是否设置成功
    """
    manager = PartitionManager(db_session, logger)

    # 创建未来分区
    manager.auto_create_partitions(table_name, months_ahead)

    # 清理旧分区
    manager.cleanup_old_partitions(table_name, keep_months)

    return True


if __name__ == "__main__":
    # 测试代码
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # 创建测试数据库
    engine = create_engine('sqlite:///:memory:')
    Session = sessionmaker(bind=engine)

    session = Session()

    # 测试分区管理
    manager = PartitionManager(session)

    # 注意：PostgreSQL才支持分区，SQLite不支持
    # 这里只是演示API使用方式
    print("分区管理器已初始化")
    print("注意：分区表功能需要PostgreSQL数据库")
