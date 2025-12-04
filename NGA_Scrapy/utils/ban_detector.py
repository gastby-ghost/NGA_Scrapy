"""
IP封禁检测和浏览器实例管理模块
用于检测IP或浏览器实例是否被封禁，并自动替换被封禁的实例
"""

import time
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging
from collections import deque

class BanType(Enum):
    """封禁类型枚举"""
    TIMEOUT = "timeout"          # 超时封禁
    CAPTCHA = "captcha"         # 验证码封禁
    RATE_LIMIT = "rate_limit"   # 频率限制封禁
    IP_BLOCK = "ip_block"       # IP直接封禁
    UNKNOWN = "unknown"         # 未知封禁

@dataclass
class BanRecord:
    """封禁记录"""
    ban_type: BanType
    first_detected: float
    last_detected: float
    detection_count: int
    error_messages: List[str]

    def is_recent(self, timeout_seconds: float = 3600) -> bool:
        """检查是否为最近的封禁记录"""
        return time.time() - self.last_detected < timeout_seconds

class BanDetector:
    """IP封禁检测器"""

    def __init__(self, logger=None, ban_threshold: int = 3, recovery_time: int = 1800):
        """
        初始化封禁检测器

        Args:
            logger: 日志记录器
            ban_threshold: 触发封禁的错误次数阈值
            recovery_time: 封禁恢复时间（秒），默认30分钟
        """
        self.logger = logger or logging.getLogger(__name__)
        self.ban_threshold = ban_threshold
        self.recovery_time = recovery_time

        # 线程安全锁
        self._lock = threading.RLock()

        # 浏览器实例状态跟踪
        self.browser_instances = {}  # {instance_id: BrowserInstance}
        self.proxy_status = {}       # {proxy_address: ProxyStatus}

        # 统计信息
        self.stats = {
            'total_bans': 0,
            'active_bans': 0,
            'recovered_instances': 0,
            'replaced_proxies': 0
        }

    def register_browser_instance(self, instance_id: int, proxy_address: Optional[str] = None):
        """注册新的浏览器实例"""
        with self._lock:
            self.browser_instances[instance_id] = {
                'instance_id': instance_id,
                'proxy_address': proxy_address,
                'status': 'active',  # active, banned, recovering
                'last_success': time.time(),
                'last_failure': None,
                'failures': deque(maxlen=10),  # 保留最近10次失败记录
                'ban_records': [],  # 历史封禁记录
                'total_requests': 0,
                'success_requests': 0
            }

            if proxy_address and proxy_address not in self.proxy_status:
                self.proxy_status[proxy_address] = {
                    'address': proxy_address,
                    'status': 'active',
                    'banned_instances': set(),
                    'last_ban_time': None,
                    'ban_count': 0,
                    'total_requests': 0,
                    'success_requests': 0
                }

        self.logger.debug(f"注册浏览器实例 {instance_id} (代理: {proxy_address or '直连'})")

    def report_success(self, instance_id: int, response_time: float = 0):
        """报告成功请求"""
        with self._lock:
            if instance_id in self.browser_instances:
                instance = self.browser_instances[instance_id]
                instance['status'] = 'active'
                instance['last_success'] = time.time()
                instance['total_requests'] += 1
                instance['success_requests'] += 1

                # 清除过期的失败记录
                self._cleanup_old_failures(instance)

                # 更新代理状态
                proxy = instance['proxy_address']
                if proxy and proxy in self.proxy_status:
                    self.proxy_status[proxy]['total_requests'] += 1
                    self.proxy_status[proxy]['success_requests'] += 1

    def report_failure(self, instance_id: int, error: Exception,
                      ban_type: Optional[BanType] = None) -> bool:
        """
        报告请求失败，检测是否为封禁

        Args:
            instance_id: 浏览器实例ID
            error: 错误对象
            ban_type: 指定的封禁类型，如果为None则自动检测

        Returns:
            bool: 是否检测到封禁
        """
        if ban_type is None:
            ban_type = self._detect_ban_type(error)

        with self._lock:
            if instance_id not in self.browser_instances:
                self.logger.warning(f"未知的浏览器实例: {instance_id}")
                return False

            instance = self.browser_instances[instance_id]
            current_time = time.time()

            # 记录失败
            failure_record = {
                'timestamp': current_time,
                'error_type': type(error).__name__,
                'error_message': str(error)[:200],
                'ban_type': ban_type
            }
            instance['failures'].append(failure_record)
            instance['last_failure'] = current_time
            instance['total_requests'] += 1

            # 更新代理状态
            proxy = instance['proxy_address']
            if proxy and proxy in self.proxy_status:
                self.proxy_status[proxy]['total_requests'] += 1

            # 检测是否达到封禁阈值
            is_banned = self._check_ban_threshold(instance, ban_type)

            if is_banned:
                self._mark_as_banned(instance_id, ban_type, str(error))
                return True

            return False

    def _detect_ban_type(self, error: Exception) -> BanType:
        """根据错误类型检测封禁类型"""
        error_message = str(error).lower()
        error_type = type(error).__name__

        if 'timeout' in error_message or 'TimeoutError' in error_type:
            return BanType.TIMEOUT
        elif 'captcha' in error_message or '验证码' in error_message:
            return BanType.CAPTCHA
        elif 'rate limit' in error_message or 'frequency' in error_message:
            return BanType.RATE_LIMIT
        elif 'blocked' in error_message or 'forbidden' in error_message or '403' in error_message:
            return BanType.IP_BLOCK
        else:
            return BanType.UNKNOWN

    def _check_ban_threshold(self, instance: Dict, ban_type: BanType) -> bool:
        """检查是否达到封禁阈值（必须是连续失败）"""
        current_time = time.time()
        recent_failures = [
            f for f in instance['failures']
            if current_time - f['timestamp'] < 300  # 5分钟内
        ]

        # 如果最近没有失败记录，不算连续
        if not recent_failures:
            return False

        # 检查最近的连续失败（必须是同类型的连续失败）
        consecutive_same_type = 0
        consecutive_total = 0

        # 从最近的一次失败开始向前检查
        for i in range(len(recent_failures) - 1, -1, -1):
            failure = recent_failures[i]

            # 检查是否是连续的（两次失败间隔不超过2分钟）
            if consecutive_total > 0:
                prev_failure = recent_failures[i + 1]
                if prev_failure['timestamp'] - failure['timestamp'] > 120:  # 超过2分钟不算连续
                    break

            consecutive_total += 1

            # 如果是同类型封禁，增加同类型计数
            if failure['ban_type'] == ban_type:
                consecutive_same_type += 1

        self.logger.debug(
            f"实例连续失败检查: 同类型{consecutive_same_type}次, 总连续{consecutive_total}次, "
            f"阈值:{self.ban_threshold}, 类型:{ban_type.value}"
        )

        # 检查连续失败条件
        # 1. 同类型的连续失败达到阈值
        if consecutive_same_type >= self.ban_threshold:
            self.logger.debug(f"✓ 同类型连续失败达到阈值: {consecutive_same_type} >= {self.ban_threshold}")
            return True

        # 2. 特殊类型检查（某些类型一次就封禁）
        if ban_type in [BanType.CAPTCHA, BanType.IP_BLOCK] and consecutive_same_type >= 1:
            self.logger.debug(f"✓ 特殊封禁类型检测: {ban_type.value}")
            return True

        # 3. 总连续失败达到阈值（任何类型）
        if consecutive_total >= self.ban_threshold + 1:  # 总阈值略高一些
            self.logger.debug(f"✓ 总连续失败达到阈值: {consecutive_total} >= {self.ban_threshold + 1}")
            return True

        self.logger.debug("✗ 未达到封禁阈值")
        return False

    def _mark_as_banned(self, instance_id: int, ban_type: BanType, error_message: str):
        """标记实例为被封禁状态"""
        current_time = time.time()
        instance = self.browser_instances[instance_id]

        # 更新实例状态
        instance['status'] = 'banned'

        # 添加封禁记录
        ban_record = BanRecord(
            ban_type=ban_type,
            first_detected=current_time,
            last_detected=current_time,
            detection_count=1,
            error_messages=[error_message[:200]]
        )

        # 检查是否有相同类型的未解决封禁
        existing_ban = None
        for record in instance['ban_records']:
            if record.ban_type == ban_type and record.is_recent(self.recovery_time):
                existing_ban = record
                break

        if existing_ban:
            # 更新现有封禁记录
            existing_ban.last_detected = current_time
            existing_ban.detection_count += 1
            existing_ban.error_messages.append(error_message[:200])
        else:
            # 创建新封禁记录
            instance['ban_records'].append(ban_record)
            self.stats['total_bans'] += 1

        # 更新代理状态
        proxy = instance['proxy_address']
        if proxy and proxy in self.proxy_status:
            self.proxy_status[proxy]['banned_instances'].add(instance_id)
            self.proxy_status[proxy]['last_ban_time'] = current_time
            self.proxy_status[proxy]['ban_count'] += 1
            self.proxy_status[proxy]['status'] = 'banned'

        self.stats['active_bans'] += 1

        self.logger.warning(
            f"🚫 实例 {instance_id} 已被封禁 "
            f"(类型: {ban_type.value}, 代理: {proxy or '直连'}, "
            f"错误: {error_message[:100]}...)"
        )

    def is_instance_banned(self, instance_id: int) -> bool:
        """检查实例是否被封禁"""
        with self._lock:
            if instance_id not in self.browser_instances:
                return False

            instance = self.browser_instances[instance_id]

            # 检查状态
            if instance['status'] == 'banned':
                # 检查是否到了恢复时间
                current_time = time.time()
                for record in instance['ban_records']:
                    if record.is_recent(self.recovery_time):
                        return True  # 仍在封禁期

                # 封禁期已过，标记为可恢复
                instance['status'] = 'recovering'
                self.stats['active_bans'] -= 1
                self.stats['recovered_instances'] += 1

                # 更新代理状态
                proxy = instance['proxy_address']
                if proxy and proxy in self.proxy_status:
                    self.proxy_status[proxy]['banned_instances'].discard(instance_id)
                    if len(self.proxy_status[proxy]['banned_instances']) == 0:
                        self.proxy_status[proxy]['status'] = 'recovering'

                self.logger.info(f"✅ 实例 {instance_id} 封禁期已过，可以重新使用")
                return False

            return False

    def is_proxy_banned(self, proxy_address: str) -> bool:
        """检查代理是否被封禁"""
        with self._lock:
            if proxy_address not in self.proxy_status:
                return False

            proxy = self.proxy_status[proxy_address]

            # 如果关联的实例大部分被封禁，则认为代理也被封禁
            if len(proxy['banned_instances']) >= 2:  # 超过2个实例被封禁
                proxy['status'] = 'banned'
                return True

            # 检查是否达到封禁阈值
            if proxy['ban_count'] >= self.ban_threshold * 2:  # 代理的阈值更高
                return True

            return False

    def get_available_instances(self) -> List[int]:
        """获取可用的浏览器实例列表"""
        with self._lock:
            available = []
            for instance_id, instance in self.browser_instances.items():
                if not self.is_instance_banned(instance_id):
                    available.append(instance_id)
            return available

    def get_available_proxies(self) -> List[str]:
        """获取可用的代理列表"""
        with self._lock:
            available = []
            for proxy_address, proxy in self.proxy_status.items():
                if not self.is_proxy_banned(proxy_address):
                    available.append(proxy_address)
            return available

    def mark_instance_replaced(self, instance_id: int, new_instance_id: int, new_proxy: Optional[str] = None):
        """标记实例已被替换"""
        with self._lock:
            if instance_id in self.browser_instances:
                # 移除旧实例
                old_instance = self.browser_instances.pop(instance_id)
                self.logger.info(f"🔄 实例 {instance_id} 已被替换为 {new_instance_id}")

            # 注册新实例
            self.register_browser_instance(new_instance_id, new_proxy)

            self.stats['replaced_proxies'] += 1

    def _cleanup_old_failures(self, instance: Dict):
        """清理过期的失败记录"""
        cutoff_time = time.time() - 3600  # 1小时前
        instance['failures'] = deque(
            [f for f in instance['failures'] if f['timestamp'] > cutoff_time],
            maxlen=10
        )

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            active_instances = sum(1 for inst in self.browser_instances.values() if inst['status'] == 'active')
            banned_instances = sum(1 for inst in self.browser_instances.values() if inst['status'] == 'banned')

            active_proxies = sum(1 for proxy in self.proxy_status.values() if proxy['status'] == 'active')
            banned_proxies = sum(1 for proxy in self.proxy_status.values() if proxy['status'] == 'banned')

            return {
                **self.stats,
                'total_instances': len(self.browser_instances),
                'active_instances': active_instances,
                'banned_instances': banned_instances,
                'total_proxies': len(self.proxy_status),
                'active_proxies': active_proxies,
                'banned_proxies': banned_proxies,
                'ban_threshold': self.ban_threshold,
                'recovery_time_minutes': self.recovery_time // 60
            }

    def get_detailed_report(self) -> str:
        """获取详细的封禁检测报告"""
        with self._lock:
            report = ["=" * 60]
            report.append("🔍 IP封禁检测报告")
            report.append("=" * 60)

            stats = self.get_stats()
            report.append(f"📊 统计信息:")
            report.append(f"  - 总实例数: {stats['total_instances']}")
            report.append(f"  - 活跃实例: {stats['active_instances']}")
            report.append(f"  - 封禁实例: {stats['banned_instances']}")
            report.append(f"  - 总代理数: {stats['total_proxies']}")
            report.append(f"  - 活跃代理: {stats['active_proxies']}")
            report.append(f"  - 封禁代理: {stats['banned_proxies']}")
            report.append(f"  - 历史封禁数: {stats['total_bans']}")
            report.append(f"  - 已恢复实例: {stats['recovered_instances']}")
            report.append(f"  - 已替换实例: {stats['replaced_proxies']}")

            # 封禁实例详情
            banned_instances = [inst for inst in self.browser_instances.values() if inst['status'] == 'banned']
            if banned_instances:
                report.append(f"\n🚫 当前封禁实例 ({len(banned_instances)}):")
                for inst in banned_instances:
                    current_ban = None
                    for record in inst['ban_records']:
                        if record.is_recent():
                            current_ban = record
                            break

                    if current_ban:
                        time_since_ban = time.time() - current_ban.last_detected
                        recovery_time_left = max(0, self.recovery_time - time_since_ban)
                        report.append(
                            f"  - 实例 {inst['instance_id']}: {current_ban.ban_type.value}, "
                            f"剩余恢复时间: {recovery_time_left//60}分钟"
                        )

            # 代理状态详情
            if self.proxy_status:
                report.append(f"\n🌐 代理状态:")
                for proxy, status in self.proxy_status.items():
                    banned_count = len(status['banned_instances'])
                    report.append(
                        f"  - {proxy[:50]}...: {status['status']}, "
                        f"封禁实例数: {banned_count}, 历史封禁: {status['ban_count']}"
                    )

            report.append("=" * 60)
            return "\n".join(report)