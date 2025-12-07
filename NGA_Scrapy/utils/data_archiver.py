#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据归档管理模块

自动清理和归档过期数据，保持数据库性能，优化存储空间。
每月执行一次，归档1个月未更新的主题及其对应回复和用户。

主要功能:
1. 按主题关联归档（主题+回复+用户）
2. 数据生命周期管理
3. 归档性能优化
4. 数据恢复机制

作者: Claude Code
日期: 2025-12-07
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from pathlib import Path
from threading import Lock


class DataArchiver:
    """数据归档管理器

    每月归档1个月未更新的主题及其关联的回复和用户
    """

    def __init__(self, db_session, archive_dir='./archive', config=None):
        """初始化数据归档器

        Args:
            db_session: SQLAlchemy会话
            archive_dir: 归档存储目录
            config: 配置字典
        """
        self.db_session = db_session
        self.archive_dir = Path(archive_dir)
        self.config = config or {}

        self.logger = logging.getLogger(__name__)

        # 确保归档目录存在
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        # 归档配置 - 简化为按主题关联归档
        self.archive_config = {
            'enabled': self.config.get('enabled', True),
            # 主题归档阈值：1个月（30天）未更新
            'archive_threshold_days': self.config.get('archive_threshold_days', 30),
            # 归档文件保留期（天）
            'archive_retention_days': self.config.get('archive_retention_days', 365),
            # 每批归档的主题数量
            'archive_batch_size': self.config.get('archive_batch_size', 500),
        }

        # 统计信息
        self.stats = {
            'archived_topics': 0,
            'archived_replies': 0,
            'archived_users': 0,
            'archive_operations': 0,
            'total_archived_size': 0,  # MB
            'last_archive_time': None,
        }

        self.lock = Lock()

    def get_topics_to_archive(self) -> List[str]:
        """获取需要归档的主题TID列表

        查找1个月未更新的主题

        Returns:
            List[str]: 需要归档的主题TID列表
        """
        try:
            from ..models import Topic

            threshold_days = self.archive_config['archive_threshold_days']
            cutoff_date = datetime.now() - timedelta(days=threshold_days)
            batch_size = self.archive_config['archive_batch_size']

            # 查询1个月未更新的主题
            topics = (
                self.db_session.query(Topic.tid)
                .filter(Topic.last_reply_date < cutoff_date.strftime('%Y-%m-%d %H:%M:%S'))
                .limit(batch_size)
                .all()
            )

            tids = [topic.tid for topic in topics]
            self.logger.info(f"找到 {len(tids)} 个需要归档的主题（{threshold_days}天未更新）")
            return tids

        except Exception as e:
            self.logger.error(f"获取归档主题失败: {e}")
            return []

    def archive_topics_with_related(self, tids: List[str]) -> Dict[str, int]:
        """归档主题及其关联的回复和用户

        Args:
            tids: 主题TID列表

        Returns:
            Dict[str, int]: 归档结果统计
        """
        if not tids:
            return {'topics': 0, 'replies': 0, 'users': 0, 'failed': 0}

        try:
            start_time = time.time()

            # 1. 导出主题数据
            topics_data = self._export_topics(tids)
            if not topics_data:
                return {'topics': 0, 'replies': 0, 'users': 0, 'failed': len(tids)}

            # 2. 获取并导出关联的回复
            replies_data = self._export_replies_by_tids(tids)

            # 3. 收集并导出关联的用户
            user_ids = self._collect_user_ids(topics_data, replies_data)
            users_data = self._export_users(user_ids)

            # 4. 创建归档文件
            archive_file = self._create_archive_file()
            if not archive_file:
                return {'topics': 0, 'replies': 0, 'users': 0, 'failed': len(tids)}

            # 5. 保存归档数据
            archive_data = {
                'archive_time': datetime.now().isoformat(),
                'archive_type': 'monthly_topic_archive',
                'threshold_days': self.archive_config['archive_threshold_days'],
                'topics': topics_data,
                'replies': replies_data,
                'users': users_data,
                'summary': {
                    'topic_count': len(topics_data.get('data', [])),
                    'reply_count': len(replies_data.get('data', [])),
                    'user_count': len(users_data.get('data', [])),
                }
            }

            try:
                with open(archive_file, 'w', encoding='utf-8') as f:
                    json.dump(archive_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.logger.error(f"保存归档文件失败: {e}")
                return {'topics': 0, 'replies': 0, 'users': 0, 'failed': len(tids)}

            # 6. 从数据库删除已归档数据
            deleted_topics = self._delete_topics(tids)
            deleted_replies = self._delete_replies_by_tids(tids)
            # 用户不删除，只归档备份

            elapsed = time.time() - start_time

            # 更新统计
            with self.lock:
                self.stats['archived_topics'] += deleted_topics
                self.stats['archived_replies'] += deleted_replies
                self.stats['archived_users'] += len(users_data.get('data', []))
                self.stats['archive_operations'] += 1
                self.stats['last_archive_time'] = datetime.now().isoformat()
                self.stats['total_archived_size'] += os.path.getsize(archive_file) / 1024 / 1024

            self.logger.info(
                f"📦 归档完成: {deleted_topics}个主题, {deleted_replies}个回复, "
                f"{len(users_data.get('data', []))}个用户备份, 耗时 {elapsed:.2f}s"
            )

            return {
                'topics': deleted_topics,
                'replies': deleted_replies,
                'users': len(users_data.get('data', [])),
                'failed': len(tids) - deleted_topics,
                'archive_file': str(archive_file)
            }

        except Exception as e:
            self.logger.error(f"归档操作失败: {e}")
            return {'topics': 0, 'replies': 0, 'users': 0, 'failed': len(tids)}

    def _export_topics(self, tids: List[str]) -> Dict:
        """导出主题数据"""
        try:
            from ..models import Topic

            topics = (
                self.db_session.query(Topic)
                .filter(Topic.tid.in_(tids))
                .all()
            )

            return {
                'export_type': 'topic',
                'count': len(topics),
                'data': [
                    {
                        'tid': topic.tid,
                        'title': topic.title,
                        'poster_id': topic.poster_id,
                        'post_time': topic.post_time,
                        're_num': topic.re_num,
                        'sampling_time': topic.sampling_time,
                        'last_reply_date': topic.last_reply_date,
                        'partition': topic.partition,
                    }
                    for topic in topics
                ]
            }

        except Exception as e:
            self.logger.error(f"导出主题数据失败: {e}")
            return {}

    def _export_replies_by_tids(self, tids: List[str]) -> Dict:
        """根据主题TID导出关联的回复"""
        try:
            from ..models import Reply

            replies = (
                self.db_session.query(Reply)
                .filter(Reply.tid.in_(tids))
                .all()
            )

            return {
                'export_type': 'reply',
                'count': len(replies),
                'data': [
                    {
                        'rid': reply.rid,
                        'tid': reply.tid,
                        'parent_rid': reply.parent_rid,
                        'content': reply.content,
                        'recommendvalue': reply.recommendvalue,
                        'poster_id': reply.poster_id,
                        'post_time': reply.post_time,
                        'image_urls': reply.image_urls,
                        'image_paths': reply.image_paths,
                        'sampling_time': reply.sampling_time,
                    }
                    for reply in replies
                ]
            }

        except Exception as e:
            self.logger.error(f"导出回复数据失败: {e}")
            return {}

    def _collect_user_ids(self, topics_data: Dict, replies_data: Dict) -> Set[str]:
        """收集主题和回复中的用户ID"""
        user_ids = set()

        # 从主题中收集
        for topic in topics_data.get('data', []):
            if topic.get('poster_id'):
                user_ids.add(topic['poster_id'])

        # 从回复中收集
        for reply in replies_data.get('data', []):
            if reply.get('poster_id'):
                user_ids.add(reply['poster_id'])

        return user_ids

    def _export_users(self, user_ids: Set[str]) -> Dict:
        """导出用户数据（仅备份，不删除）"""
        if not user_ids:
            return {'export_type': 'user', 'count': 0, 'data': []}

        try:
            from ..models import User

            users = (
                self.db_session.query(User)
                .filter(User.uid.in_(list(user_ids)))
                .all()
            )

            return {
                'export_type': 'user',
                'count': len(users),
                'data': [
                    {
                        'uid': user.uid,
                        'name': user.name,
                        'user_group': user.user_group,
                        'prestige': user.prestige,
                        'reg_date': user.reg_date,
                        'history_re_num': user.history_re_num,
                    }
                    for user in users
                ]
            }

        except Exception as e:
            self.logger.error(f"导出用户数据失败: {e}")
            return {}

    def _create_archive_file(self) -> Optional[Path]:
        """创建归档文件"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            archive_file = self.archive_dir / f"monthly_archive_{timestamp}.json"
            return archive_file
        except Exception as e:
            self.logger.error(f"创建归档文件失败: {e}")
            return None

    def _delete_topics(self, tids: List[str]) -> int:
        """删除主题"""
        try:
            from ..models import Topic

            deleted = (
                self.db_session.query(Topic)
                .filter(Topic.tid.in_(tids))
                .delete(synchronize_session=False)
            )
            self.db_session.commit()
            return deleted

        except Exception as e:
            self.logger.error(f"删除主题失败: {e}")
            self.db_session.rollback()
            return 0

    def _delete_replies_by_tids(self, tids: List[str]) -> int:
        """删除主题关联的回复"""
        try:
            from ..models import Reply

            deleted = (
                self.db_session.query(Reply)
                .filter(Reply.tid.in_(tids))
                .delete(synchronize_session=False)
            )
            self.db_session.commit()
            return deleted

        except Exception as e:
            self.logger.error(f"删除回复失败: {e}")
            self.db_session.rollback()
            return 0

    def auto_archive(self) -> Dict[str, int]:
        """自动执行月度数据归档

        Returns:
            Dict[str, int]: 归档统计
        """
        if not self.archive_config['enabled']:
            self.logger.info("数据归档已禁用")
            return {'topics': 0, 'replies': 0, 'users': 0, 'failed': 0}

        self.logger.info("🔄 开始月度数据归档...")

        # 获取需要归档的主题
        tids = self.get_topics_to_archive()

        if not tids:
            self.logger.info("没有需要归档的数据")
            return {'topics': 0, 'replies': 0, 'users': 0, 'failed': 0}

        # 执行关联归档
        result = self.archive_topics_with_related(tids)

        return result

    def restore_archive(self, archive_file: str) -> Dict[str, int]:
        """从归档文件恢复数据

        Args:
            archive_file: 归档文件路径

        Returns:
            Dict[str, int]: 恢复结果统计
        """
        try:
            if not os.path.exists(archive_file):
                self.logger.error(f"归档文件不存在: {archive_file}")
                return {'topics': 0, 'replies': 0, 'users': 0, 'failed': 0}

            with open(archive_file, 'r', encoding='utf-8') as f:
                archive_data = json.load(f)

            restored_topics = 0
            restored_replies = 0
            restored_users = 0

            # 恢复主题
            for topic in archive_data.get('topics', {}).get('data', []):
                try:
                    self._restore_topic(topic)
                    restored_topics += 1
                except Exception as e:
                    self.logger.error(f"恢复主题失败: {e}")

            # 恢复回复
            for reply in archive_data.get('replies', {}).get('data', []):
                try:
                    self._restore_reply(reply)
                    restored_replies += 1
                except Exception as e:
                    self.logger.error(f"恢复回复失败: {e}")

            # 恢复用户（如果不存在）
            for user in archive_data.get('users', {}).get('data', []):
                try:
                    self._restore_user(user)
                    restored_users += 1
                except Exception as e:
                    self.logger.error(f"恢复用户失败: {e}")

            self.db_session.commit()

            self.logger.info(
                f"🔄 恢复完成: {restored_topics}个主题, "
                f"{restored_replies}个回复, {restored_users}个用户"
            )

            return {
                'topics': restored_topics,
                'replies': restored_replies,
                'users': restored_users,
                'failed': 0
            }

        except Exception as e:
            self.logger.error(f"恢复归档数据失败: {e}")
            self.db_session.rollback()
            return {'topics': 0, 'replies': 0, 'users': 0, 'failed': 1}

    def _restore_topic(self, topic_data: Dict):
        """恢复主题数据"""
        from ..models import Topic
        topic = Topic(**topic_data)
        self.db_session.merge(topic)

    def _restore_reply(self, reply_data: Dict):
        """恢复回复数据"""
        from ..models import Reply
        reply = Reply(**reply_data)
        self.db_session.merge(reply)

    def _restore_user(self, user_data: Dict):
        """恢复用户数据"""
        from ..models import User
        user = User(**user_data)
        self.db_session.merge(user)

    def cleanup_old_archives(self, retention_days: int = None) -> int:
        """清理过期的归档文件

        Args:
            retention_days: 归档文件保留天数，默认使用配置值

        Returns:
            int: 清理的文件数量
        """
        try:
            if retention_days is None:
                retention_days = self.archive_config['archive_retention_days']

            cutoff_date = datetime.now() - timedelta(days=retention_days)
            cleaned_count = 0

            for archive_file in self.archive_dir.glob("*.json"):
                file_mtime = datetime.fromtimestamp(archive_file.stat().st_mtime)

                if file_mtime < cutoff_date:
                    archive_file.unlink()
                    cleaned_count += 1
                    self.logger.debug(f"删除过期归档文件: {archive_file}")

            if cleaned_count > 0:
                self.logger.info(f"🧹 清理了 {cleaned_count} 个过期归档文件")

            return cleaned_count

        except Exception as e:
            self.logger.error(f"清理归档文件失败: {e}")
            return 0

    def get_archive_stats(self) -> Dict:
        """获取归档统计信息"""
        with self.lock:
            total_size = sum(
                f.stat().st_size for f in self.archive_dir.glob("*.json")
            ) / 1024 / 1024  # MB

            return {
                'archived_topics': self.stats['archived_topics'],
                'archived_replies': self.stats['archived_replies'],
                'archived_users': self.stats['archived_users'],
                'archive_operations': self.stats['archive_operations'],
                'total_archived_size_mb': f"{self.stats['total_archived_size']:.2f}",
                'current_archive_size_mb': f"{total_size:.2f}",
                'last_archive_time': self.stats['last_archive_time'],
                'archive_files': len(list(self.archive_dir.glob("*.json"))),
                'config': self.archive_config,
            }

    def generate_archive_report(self) -> str:
        """生成归档报告"""
        stats = self.get_archive_stats()

        report = []
        report.append("=" * 60)
        report.append("📦 月度数据归档报告")
        report.append("=" * 60)
        report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        report.append("📊 归档统计:")
        report.append(f"  已归档主题: {stats['archived_topics']:,} 个")
        report.append(f"  已归档回复: {stats['archived_replies']:,} 个")
        report.append(f"  已备份用户: {stats['archived_users']:,} 个")
        report.append(f"  归档操作: {stats['archive_operations']} 次")
        report.append("")

        report.append("💾 存储统计:")
        report.append(f"  历史归档大小: {stats['total_archived_size_mb']} MB")
        report.append(f"  当前归档大小: {stats['current_archive_size_mb']} MB")
        report.append(f"  归档文件数: {stats['archive_files']} 个")
        report.append("")

        if stats['last_archive_time']:
            report.append(f"⏰ 最后归档时间: {stats['last_archive_time']}")
            report.append("")

        report.append("⚙️ 归档配置:")
        report.append(f"  启用状态: {stats['config']['enabled']}")
        report.append(f"  归档阈值: {stats['config']['archive_threshold_days']} 天未更新")
        report.append(f"  归档保留期: {stats['config']['archive_retention_days']} 天")
        report.append(f"  批处理大小: {stats['config']['archive_batch_size']} 个主题/批")
        report.append("")

        report.append("=" * 60)
        return "\n".join(report)


# 便捷函数
def create_data_archiver(db_session, archive_dir='./archive', config=None):
    """创建数据归档器实例"""
    return DataArchiver(db_session, archive_dir, config)


def run_monthly_archive(db_session, archive_dir='./archive', config=None):
    """便捷函数：执行月度归档"""
    archiver = DataArchiver(db_session, archive_dir, config)
    return archiver.auto_archive()


if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine('sqlite:///:memory:')
    Session = sessionmaker(bind=engine)
    session = Session()

    archiver = DataArchiver(session, './test_archive', {
        'enabled': True,
        'archive_threshold_days': 30,
    })

    print(archiver.generate_archive_report())
