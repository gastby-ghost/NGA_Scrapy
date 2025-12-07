#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询优化器模块

提供高效的数据库查询策略，包括EXISTS替代IN查询、增量同步机制等。

主要功能:
1. EXISTS查询优化（替代IN查询）
2. 增量同步机制
3. 查询计划分析
4. 时间戳优化查询
5. 批量存在性检查

作者: Claude Code
日期: 2025-12-07
"""

import time
import logging
from sqlalchemy import exists, and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError


class QueryOptimizer:
    """查询优化器"""

    def __init__(self, db_session: Session, logger=None):
        """初始化查询优化器

        Args:
            db_session: SQLAlchemy会话
            logger: 日志记录器
        """
        self.db_session = db_session
        self.logger = logger or logging.getLogger(__name__)

    def check_topics_exist_exists(self, tids):
        """使用EXISTS查询检查主题是否存在（优化版本）

        对于大量TID，EXISTS查询比IN查询更高效，特别是当表有索引时。

        Args:
            tids: 主题ID列表

        Returns:
            set: 存在的主题ID集合
        """
        if not tids:
            return set()

        try:
            from ..models import Topic
            start_time = time.time()

            # 使用EXISTS子查询检查每个TID是否存在
            # 这种方式对于大量数据更高效
            existing_tids = set()

            # 对于少量TID，使用IN查询
            if len(tids) <= 10:
                topics = self.db_session.query(Topic.tid).filter(Topic.tid.in_(tids)).all()
                existing_tids = {topic.tid for topic in topics}
            else:
                # 对于大量TID，使用分批EXISTS查询
                batch_size = 100
                for i in range(0, len(tids), batch_size):
                    batch_tids = tids[i:i + batch_size]

                    # 构建EXISTS查询
                    for tid in batch_tids:
                        exists_query = self.db_session.query(exists().where(Topic.tid == tid)).scalar()
                        if exists_query:
                            existing_tids.add(tid)

            elapsed = time.time() - start_time
            self.logger.debug(
                f"🔍 [EXISTS查询] 检查{len(tids)}个主题存在性，"
                f"找到{len(existing_tids)}个存在，耗时{elapsed:.3f}s"
            )

            return existing_tids

        except SQLAlchemyError as e:
            self.logger.error(f"EXISTS查询出错: {e}")
            return set()
        except Exception as e:
            self.logger.error(f"EXISTS查询发生意外错误: {e}")
            return set()

    def get_updated_topics_since(self, last_sync_time, limit=1000):
        """获取指定时间后更新的主题（增量同步）

        Args:
            last_sync_time: 上次同步时间（字符串格式）
            limit: 最大返回数量

        Returns:
            list: 更新的主题列表
        """
        if not last_sync_time:
            return []

        try:
            from ..models import Topic
            start_time = time.time()

            # 使用索引优化查询（last_reply_date字段有索引）
            # 只获取比上次同步时间更新的主题
            topics = (
                self.db_session.query(Topic)
                .filter(Topic.last_reply_date > last_sync_time)
                .order_by(Topic.last_reply_date.desc())
                .limit(limit)
                .all()
            )

            elapsed = time.time() - start_time
            self.logger.info(
                f"📈 [增量同步] 查询{limit}个最新更新主题，"
                f"找到{len(topics)}个，耗时{elapsed:.3f}s"
            )

            return topics

        except SQLAlchemyError as e:
            self.logger.error(f"增量同步查询出错: {e}")
            return []
        except Exception as e:
            self.logger.error(f"增量同步查询发生意外错误: {e}")
            return []

    def get_topic_count_by_time_range(self, start_time, end_time=None):
        """按时间范围获取主题数量统计

        Args:
            start_time: 开始时间
            end_time: 结束时间，None表示到现在

        Returns:
            int: 主题数量
        """
        try:
            from ..models import Topic

            query = self.db_session.query(Topic).filter(Topic.post_time >= start_time)

            if end_time:
                query = query.filter(Topic.post_time <= end_time)

            count = query.count()

            self.logger.debug(
                f"📊 [时间统计] {start_time} 到 {end_time or '现在'} "
                f"共{count}个主题"
            )

            return count

        except SQLAlchemyError as e:
            self.logger.error(f"时间范围统计查询出错: {e}")
            return 0
        except Exception as e:
            self.logger.error(f"时间范围统计查询发生意外错误: {e}")
            return 0

    def batch_check_and_update(self, tids, update_callback=None):
        """批量检查并更新主题（高级优化）

        结合EXISTS查询、增量更新和批量处理，提供最高效的数据同步方案。

        Args:
            tids: 主题ID列表
            update_callback: 更新回调函数，接收(topic, is_new)参数

        Returns:
            dict: {
                'existing': existing_tids_set,
                'new': new_tids_set,
                'updated': updated_topics_list,
                'skipped': skipped_tids_list
            }
        """
        if not tids:
            return {
                'existing': set(),
                'new': set(),
                'updated': [],
                'skipped': []
            }

        try:
            from ..models import Topic
            import time

            start_time = time.time()

            # 第一步：使用EXISTS查询检查存在性
            existing_tids = self.check_topics_exist_exists(tids)
            new_tids = set(tids) - existing_tids

            # 第二步：获取需要更新的主题（已存在但可能有更新）
            topics_to_update = []
            if existing_tids:
                # 批量获取已存在主题的详细信息
                batch_size = 100
                for i in range(0, len(existing_tids), batch_size):
                    batch = list(existing_tids)[i:i + batch_size]
                    topics = (
                        self.db_session.query(Topic)
                        .filter(Topic.tid.in_(batch))
                        .all()
                    )
                    topics_to_update.extend(topics)

            # 第三步：执行更新回调
            updated_topics = []
            skipped_tids = []

            if update_callback:
                for topic in topics_to_update:
                    try:
                        is_updated = update_callback(topic)
                        if is_updated:
                            updated_topics.append(topic)
                    except Exception as e:
                        self.logger.error(f"更新回调执行失败 (tid={topic.tid}): {e}")
                        skipped_tids.append(topic.tid)

            elapsed = time.time() - start_time

            # 统计信息
            self.logger.info(
                f"🔄 [批量优化] 处理{len(tids)}个主题: "
                f"存在{len(existing_tids)}个, 新增{len(new_tids)}个, "
                f"更新{len(updated_topics)}个, 跳过{len(skipped_tids)}个, "
                f"耗时{elapsed:.3f}s"
            )

            return {
                'existing': existing_tids,
                'new': new_tids,
                'updated': updated_topics,
                'skipped': skipped_tids
            }

        except Exception as e:
            self.logger.error(f"批量检查更新失败: {e}")
            return {
                'existing': set(),
                'new': set(),
                'updated': [],
                'skipped': tids
            }

    def analyze_query_plan(self, query):
        """分析查询计划（PostgreSQL特有）

        Args:
            query: SQLAlchemy查询对象

        Returns:
            dict: 查询计划信息
        """
        try:
            # 获取原生SQL语句
            sql = str(query.statement.compile(
                compile_kwargs={"literal_binds": True}
            ))

            # 执行EXPLAIN ANALYZE
            explain_query = f"EXPLAIN ANALYZE {sql}"
            result = self.db_session.execute(explain_query)

            plan_info = []
            for row in result:
                plan_info.append(row[0])

            self.logger.debug(f"📋 [查询计划] {sql}")
            self.logger.debug(f"📊 [执行计划]\n" + "\n".join(plan_info))

            return {
                'sql': sql,
                'plan': plan_info,
                'cost': self._extract_cost(plan_info)
            }

        except Exception as e:
            self.logger.error(f"查询计划分析失败: {e}")
            return None

    def _extract_cost(self, plan_info):
        """从执行计划中提取成本信息"""
        try:
            for line in plan_info:
                if 'Planning Time:' in line:
                    return {'planning_time': line}
                elif 'Execution Time:' in line:
                    return {'execution_time': line}
            return {}
        except Exception:
            return {}

    def optimize_batch_query(self, tids, use_exists=True, use_cache=True):
        """优化的批量查询入口

        自动选择最优查询策略：
        1. 少量数据（<10）：IN查询
        2. 中等数据（10-1000）：分批IN查询
        3. 大量数据（>1000）：EXISTS查询

        Args:
            tids: 主题ID列表
            use_exists: 是否使用EXISTS查询（大量数据时）
            use_cache: 是否使用缓存

        Returns:
            dict: 查询结果统计
        """
        if not tids:
            return {'strategy': 'none', 'count': 0, 'time': 0}

        start_time = time.time()

        # 根据数据量选择策略
        if len(tids) < 10:
            strategy = 'in_query'
        elif len(tids) <= 1000:
            strategy = 'batch_in_query'
        elif use_exists:
            strategy = 'exists_query'
        else:
            strategy = 'batch_in_query'

        # 执行查询
        if strategy == 'exists_query':
            existing = self.check_topics_exist_exists(tids)
            count = len(existing)
        else:
            # 使用IN查询
            from ..models import Topic
            topics = self.db_session.query(Topic).filter(Topic.tid.in_(tids)).all()
            count = len(topics)

        elapsed = time.time() - start_time

        self.logger.info(
            f"🎯 [查询优化] 使用策略: {strategy}, "
            f"查询{len(tids)}个主题, 找到{count}个, 耗时{elapsed:.3f}s"
        )

        return {
            'strategy': strategy,
            'count': count,
            'time': elapsed,
            'tids': tids
        }


# 便捷函数
def create_query_optimizer(db_session, logger=None):
    """创建查询优化器实例"""
    return QueryOptimizer(db_session, logger)


def batch_exists_query(db_session, tids, logger=None):
    """便捷函数：批量EXISTS查询"""
    optimizer = QueryOptimizer(db_session, logger)
    return optimizer.check_topics_exist_exists(tids)


def incremental_sync(db_session, last_sync_time, logger=None):
    """便捷函数：增量同步"""
    optimizer = QueryOptimizer(db_session, logger)
    return optimizer.get_updated_topics_since(last_sync_time)


if __name__ == "__main__":
    # 测试代码
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # 创建测试数据库
    engine = create_engine('sqlite:///:memory:')
    Session = sessionmaker(bind=engine)

    # 创建测试数据
    from ..models import Base, Topic
    Base.metadata.create_all(engine)

    session = Session()

    # 添加测试数据
    for i in range(100):
        topic = Topic(
            tid=f'test_{i}',
            title=f'Test Topic {i}',
            post_time='2025-01-01 00:00:00',
            last_reply_date='2025-01-01 00:00:00',
            re_num=0
        )
        session.add(topic)

    session.commit()

    # 测试EXISTS查询
    optimizer = QueryOptimizer(session)
    test_tids = [f'test_{i}' for i in range(50)]
    existing = optimizer.check_topics_exist_exists(test_tids)
    print(f"存在的主题: {len(existing)}/{len(test_tids)}")

    # 测试查询计划分析
    query = session.query(Topic).filter(Topic.tid.in_(test_tids))
    plan = optimizer.analyze_query_plan(query)
    print(f"查询计划: {plan}")
