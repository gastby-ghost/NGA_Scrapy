#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库查询性能监控模块

提供实时查询性能监控、慢查询告警、性能统计等功能。

主要功能:
1. 查询耗时统计（平均、95分位、99分位）
2. 慢查询告警和日志
3. 查询吞吐量监控
4. 性能报告生成
5. 历史性能数据分析

作者: Claude Code
日期: 2025-12-07
"""

import time
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict, deque
from threading import Lock
import logging


class QueryMonitor:
    """查询性能监控器"""

    def __init__(self, log_file='query_performance.log'):
        self.logger = logging.getLogger(__name__)
        self.log_file = log_file
        self.lock = Lock()

        # 查询统计数据
        self.query_stats = {
            'total_queries': 0,
            'total_time': 0.0,
            'min_time': float('inf'),
            'max_time': 0.0,
            'query_times': deque(maxlen=1000),  # 保存最近1000次查询耗时
            'slow_queries': deque(maxlen=100),  # 保存最近100次慢查询
            'batch_stats': defaultdict(int),  # 批次大小统计
            'hourly_stats': defaultdict(lambda: {'count': 0, 'total_time': 0.0}),
        }

        # 慢查询阈值（秒）
        self.slow_query_threshold = 0.5  # 500ms
        self.critical_slow_threshold = 2.0  # 2000ms

        # 性能告警配置
        self.alert_config = {
            'enable_alerts': True,
            'alert_cooldown': 300,  # 5分钟内不重复告警
            'last_alert_time': 0,
        }

    def record_query(self, query_time, query_type='batch', batch_size=None, topic_count=None):
        """记录一次查询的性能数据

        Args:
            query_time: 查询耗时（秒）
            query_type: 查询类型（'batch', 'single', 'exists'等）
            batch_size: 批次大小
            topic_count: 查询的主题数量
        """
        with self.lock:
            # 更新基础统计
            self.query_stats['total_queries'] += 1
            self.query_stats['total_time'] += query_time
            self.query_stats['min_time'] = min(self.query_stats['min_time'], query_time)
            self.query_stats['max_time'] = max(self.query_stats['max_time'], query_time)

            # 保存查询耗时
            self.query_stats['query_times'].append(query_time)

            # 记录批次大小统计
            if batch_size:
                self.query_stats['batch_stats'][batch_size] += 1

            # 记录每小时统计
            now = datetime.now()
            hour_key = now.strftime('%Y-%m-%d %H:00')
            self.query_stats['hourly_stats'][hour_key]['count'] += 1
            self.query_stats['hourly_stats'][hour_key]['total_time'] += query_time

            # 慢查询检查
            if query_time > self.slow_query_threshold:
                self._record_slow_query(query_time, query_type, batch_size, topic_count)

    def _record_slow_query(self, query_time, query_type, batch_size, topic_count):
        """记录慢查询"""
        slow_query_info = {
            'timestamp': datetime.now().isoformat(),
            'query_time': query_time,
            'query_type': query_type,
            'batch_size': batch_size,
            'topic_count': topic_count,
        }

        self.query_stats['slow_queries'].append(slow_query_info)

        # 慢查询告警
        if self.alert_config['enable_alerts']:
            self._send_alert(slow_query_info)

    def _send_alert(self, slow_query_info):
        """发送慢查询告警"""
        now = time.time()

        # 冷却期检查
        if now - self.alert_config['last_alert_time'] < self.alert_config['alert_cooldown']:
            return

        self.alert_config['last_alert_time'] = now

        # 生成告警消息
        alert_msg = (
            f"⚠️ [慢查询告警] 检测到慢查询！\n"
            f"  查询耗时: {slow_query_info['query_time']:.3f}s\n"
            f"  查询类型: {slow_query_info['query_type']}\n"
            f"  批次大小: {slow_query_info.get('batch_size', 'N/A')}\n"
            f"  主题数量: {slow_query_info.get('topic_count', 'N/A')}\n"
            f"  时间: {slow_query_info['timestamp']}\n"
        )

        self.logger.warning(alert_msg)

        # 写入日志文件
        self._write_to_log(alert_msg)

    def _write_to_log(self, message):
        """写入日志文件"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat()}] {message}\n")
        except Exception as e:
            self.logger.error(f"写入性能日志失败: {e}")

    def get_stats(self):
        """获取当前性能统计"""
        with self.lock:
            stats = self.query_stats.copy()

            # 计算平均耗时
            if stats['total_queries'] > 0:
                stats['avg_time'] = stats['total_time'] / stats['total_queries']
            else:
                stats['avg_time'] = 0

            # 计算分位数
            if stats['query_times']:
                query_times_list = sorted(stats['query_times'])
                stats['p50_time'] = self._percentile(query_times_list, 50)
                stats['p95_time'] = self._percentile(query_times_list, 95)
                stats['p99_time'] = self._percentile(query_times_list, 99)
            else:
                stats['p50_time'] = stats['p95_time'] = stats['p99_time'] = 0

            return stats

    def _percentile(self, data, percentile):
        """计算百分位数"""
        if not data:
            return 0

        index = (percentile / 100.0) * (len(data) - 1)
        if index.is_integer():
            return data[int(index)]
        else:
            lower = data[int(index)]
            upper = data[int(index) + 1]
            return lower + (upper - lower) * (index - int(index))

    def generate_report(self):
        """生成性能报告"""
        stats = self.get_stats()

        report = []
        report.append("=" * 80)
        report.append("📊 数据库查询性能报告")
        report.append("=" * 80)
        report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        # 基础统计
        report.append("📈 基础统计:")
        report.append(f"  总查询次数: {stats['total_queries']:,}")
        report.append(f"  总耗时: {stats['total_time']:.3f}s")
        report.append(f"  平均耗时: {stats['avg_time']:.3f}s")
        report.append(f"  最小耗时: {stats['min_time']:.3f}s")
        report.append(f"  最大耗时: {stats['max_time']:.3f}s")
        report.append("")

        # 分位数统计
        report.append("📊 分位数统计:")
        report.append(f"  50分位: {stats['p50_time']:.3f}s")
        report.append(f"  95分位: {stats['p95_time']:.3f}s")
        report.append(f"  99分位: {stats['p99_time']:.3f}s")
        report.append("")

        # 批次大小统计
        if stats['batch_stats']:
            report.append("📦 批次大小统计:")
            for batch_size, count in sorted(stats['batch_stats'].items()):
                report.append(f"  批次大小 {batch_size}: {count} 次")
            report.append("")

        # 慢查询统计
        slow_query_count = len(stats['slow_queries'])
        if slow_query_count > 0:
            report.append(f"⚠️ 慢查询统计 (>{self.slow_query_threshold}s): {slow_query_count} 次")
            report.append("  最近5次慢查询:")
            for i, sq in enumerate(list(stats['slow_queries'])[-5:], 1):
                report.append(
                    f"    {i}. {sq['query_time']:.3f}s - "
                    f"{sq['query_type']} - {sq['timestamp']}"
                )
            report.append("")
        else:
            report.append("✅ 无慢查询记录")
            report.append("")

        # 每小时统计
        if stats['hourly_stats']:
            report.append("⏰ 最近6小时统计:")
            for hour, hour_stats in sorted(stats['hourly_stats'].items())[-6:]:
                avg_time = hour_stats['total_time'] / hour_stats['count'] if hour_stats['count'] > 0 else 0
                report.append(
                    f"  {hour}: {hour_stats['count']} 次查询, "
                    f"平均 {avg_time:.3f}s, 总计 {hour_stats['total_time']:.3f}s"
                )
            report.append("")

        # 性能评估
        report.append("🎯 性能评估:")
        if stats['avg_time'] < 0.1:
            report.append("  ✅ 查询性能优秀 (平均 < 100ms)")
        elif stats['avg_time'] < 0.5:
            report.append("  ✅ 查询性能良好 (平均 < 500ms)")
        elif stats['avg_time'] < 1.0:
            report.append("  ⚠️ 查询性能一般 (平均 < 1s)")
        else:
            report.append("  🚨 查询性能较差 (平均 >= 1s)")

        if stats['p95_time'] > 1.0:
            report.append("  ⚠️ 95分位耗时较高，建议优化")

        report.append("")
        report.append("=" * 80)

        return "\n".join(report)

    def save_stats_to_file(self, filename=None):
        """保存统计数据到文件"""
        if filename is None:
            filename = f"query_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        stats = self.get_stats()

        # 转换deque为list以便JSON序列化
        stats['query_times'] = list(stats['query_times'])
        stats['slow_queries'] = list(stats['slow_queries'])

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            self.logger.info(f"性能统计数据已保存到: {filename}")
            return filename
        except Exception as e:
            self.logger.error(f"保存性能统计数据失败: {e}")
            return None

    def reset_stats(self):
        """重置统计数据"""
        with self.lock:
            self.query_stats = {
                'total_queries': 0,
                'total_time': 0.0,
                'min_time': float('inf'),
                'max_time': 0.0,
                'query_times': deque(maxlen=1000),
                'slow_queries': deque(maxlen=100),
                'batch_stats': defaultdict(int),
                'hourly_stats': defaultdict(lambda: {'count': 0, 'total_time': 0.0}),
            }
            self.logger.info("性能统计数据已重置")


# 全局监控实例
_query_monitor = None


def get_monitor():
    """获取全局监控实例"""
    global _query_monitor
    if _query_monitor is None:
        _query_monitor = QueryMonitor()
    return _query_monitor


def query_timer(query_type='batch', batch_size=None, topic_count=None):
    """查询计时装饰器

    使用示例:
        @query_timer('batch', batch_size=100)
        def batch_query():
            # 执行查询
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            monitor = get_monitor()
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.time() - start_time
                monitor.record_query(
                    query_time=elapsed,
                    query_type=query_type,
                    batch_size=batch_size,
                    topic_count=topic_count
                )

        return wrapper
    return decorator


# 便捷函数
def record_batch_query(query_time, batch_size, topic_count):
    """记录批次查询"""
    get_monitor().record_query(query_time, 'batch', batch_size, topic_count)


def record_single_query(query_time, topic_count):
    """记录单条查询"""
    get_monitor().record_query(query_time, 'single', batch_size=1, topic_count=topic_count)


def record_exists_query(query_time, topic_count):
    """记录EXISTS查询"""
    get_monitor().record_query(query_time, 'exists', batch_size=1, topic_count=topic_count)


def get_performance_report():
    """获取性能报告"""
    return get_monitor().generate_report()


def save_performance_stats(filename=None):
    """保存性能统计"""
    return get_monitor().save_stats_to_file(filename)


if __name__ == "__main__":
    # 测试代码
    import random

    monitor = QueryMonitor()

    # 模拟查询
    print("模拟查询性能监控...")
    for i in range(100):
        query_time = random.uniform(0.01, 0.5)
        monitor.record_query(query_time, 'batch', 100, 100)

    # 生成报告
    print(monitor.generate_report())

    # 保存统计
    monitor.save_stats_to_file('test_query_stats.json')
