"""
浏览器实例自动管理器
负责自动检测、隔离和替换被封禁的浏览器实例
"""

import time
import threading
from typing import Dict, List, Optional, Callable
import logging
from queue import Queue, Empty
from dataclasses import dataclass
from .ban_detector import BanDetector, BanType

@dataclass
class ReplacementTask:
    """替换任务"""
    failed_instance_id: int
    creation_time: float
    priority: int  # 1=高优先级, 2=中优先级, 3=低优先级

class BrowserInstanceManager:
    """浏览器实例自动管理器"""

    def __init__(self,
                 max_instances: int = 4,
                 ban_detector: Optional[BanDetector] = None,
                 replacement_callback: Optional[Callable] = None,
                 proxy_manager=None,
                 logger=None):
        """
        初始化实例管理器

        Args:
            max_instances: 最大实例数
            ban_detector: 封禁检测器
            replacement_callback: 实例替换回调函数
            proxy_manager: 代理管理器
            logger: 日志记录器
        """
        self.max_instances = max_instances
        self.ban_detector = ban_detector or BanDetector(logger=logger)
        self.replacement_callback = replacement_callback
        self.proxy_manager = proxy_manager
        self.logger = logger or logging.getLogger(__name__)

        # 线程安全
        self._lock = threading.RLock()

        # 管理器状态
        self._running = False
        self._monitor_thread = None
        self._replacement_thread = None

        # 任务队列
        self._replacement_queue = Queue()

        # 统计信息
        self.stats = {
            'total_replacements': 0,
            'successful_replacements': 0,
            'failed_replacements': 0,
            'manual_replacements': 0,
            'auto_replacements': 0
        }

    def start(self):
        """启动管理器"""
        if self._running:
            self.logger.warning("实例管理器已在运行")
            return

        self._running = True
        self.logger.info("🚀 启动浏览器实例管理器")

        # 启动监控线程
        self._monitor_thread = threading.Thread(
            target=self._monitor_worker,
            name="InstanceMonitor",
            daemon=True
        )
        self._monitor_thread.start()

        # 启动替换线程
        self._replacement_thread = threading.Thread(
            target=self._replacement_worker,
            name="InstanceReplacer",
            daemon=True
        )
        self._replacement_thread.start()

    def stop(self):
        """停止管理器"""
        if not self._running:
            return

        self._running = False
        self.logger.info("🛑 正在停止浏览器实例管理器...")

        # 等待线程结束
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        if self._replacement_thread and self._replacement_thread.is_alive():
            self._replacement_thread.join(timeout=5)

        self.logger.info("✅ 浏览器实例管理器已停止")

    def register_instance(self, instance_id: int, proxy_address: Optional[str] = None):
        """注册新实例"""
        self.ban_detector.register_browser_instance(instance_id, proxy_address)

    def report_success(self, instance_id: int, response_time: float = 0):
        """报告成功请求"""
        self.ban_detector.report_success(instance_id, response_time)

    def report_failure(self, instance_id: int, error: Exception) -> bool:
        """报告失败请求，返回是否检测到封禁"""
        is_banned = self.ban_detector.report_failure(instance_id, error)

        if is_banned:
            # 自动加入替换队列
            self._schedule_replacement(instance_id, priority=1)

        return is_banned

    def request_replacement(self, instance_id: int, manual: bool = False):
        """手动请求替换实例"""
        if manual:
            self.stats['manual_replacements'] += 1
            self.logger.info(f"📝 收到手动替换请求: 实例 {instance_id}")

        self._schedule_replacement(instance_id, priority=1 if manual else 2)

    def _schedule_replacement(self, instance_id: int, priority: int = 2):
        """调度实例替换"""
        task = ReplacementTask(
            failed_instance_id=instance_id,
            creation_time=time.time(),
            priority=priority
        )

        # 将任务加入队列（按优先级插入）
        if priority == 1:
            # 高优先级任务直接加入队列前端
            temp_tasks = []
            try:
                while True:
                    temp_tasks.append(self._replacement_queue.get_nowait())
            except Empty:
                pass

            self._replacement_queue.put(task)
            for temp_task in temp_tasks:
                self._replacement_queue.put(temp_task)
        else:
            # 普通任务加入队列末尾
            self._replacement_queue.put(task)

        self.logger.debug(f"📋 已调度实例替换: {instance_id} (优先级: {priority})")

    def _monitor_worker(self):
        """监控工作线程"""
        self.logger.info("👁️ 实例监控线程已启动")

        while self._running:
            try:
                # 每1分钟检查一次，更及时的监控
                for _ in range(6):  # 1分钟 = 60秒，每次检查间隔10秒
                    if not self._running:
                        return
                    time.sleep(10)

                # 检查所有实例状态
                self._check_instances_health()

                # 每15分钟输出一次统计报告
                current_minutes = int(time.time()) // 60
                if current_minutes % 15 == 0:
                    self._log_status_report()

            except Exception as e:
                self.logger.error(f"监控线程出错: {e}")
                if not self._running:
                    break
                time.sleep(30)  # 出错后等待30秒再继续

        self.logger.info("👁️ 实例监控线程已退出")

    def _check_instances_health(self):
        """检查实例健康状态"""
        try:
            # 获取所有可用实例
            available_instances = self.ban_detector.get_available_instances()
            self.logger.info(f"📊 [实例健康检查] 当前可用实例数: {len(available_instances)}")
            
            # 【诊断日志】详细记录实例状态
            all_instances = self.ban_detector.browser_instances
            active_count = sum(1 for inst in all_instances.values() if inst.get('status') == 'active')
            banned_count = sum(1 for inst in all_instances.values() if inst.get('status') == 'banned')
            unknown_count = len(all_instances) - active_count - banned_count
            
            self.logger.info(f"📊 [实例状态详情] 总计: {len(all_instances)}, 活跃: {active_count}, 封禁: {banned_count}, 未知: {unknown_count}")

            # 如果可用实例太少，检查是否需要强制替换
            min_available = max(2, self.max_instances // 3)  # 至少需要2个，或总数的1/3
            if len(available_instances) < min_available:
                self.logger.warning(
                    f"⚠️ 可用实例过少 ({len(available_instances)}/{self.max_instances})，"
                    f"低于最小要求 {min_available}，开始强制替换"
                )

                # 强制替换一些有问题的实例
                self._force_replace_problematic_instances()
            elif len(available_instances) < self.max_instances * 0.6:  # 60%警告阈值
                self.logger.info(
                    f"ℹ️ 可用实例偏少 ({len(available_instances)}/{self.max_instances})，"
                    "建议关注实例状态"
                )

        except Exception as e:
            self.logger.error(f"检查实例健康状态时出错: {e}")

    def _force_replace_problematic_instances(self):
        """强制替换有问题的实例"""
        try:
            # 获取所有实例的状态
            all_instances = self.ban_detector.browser_instances

            self.logger.info(f"🔍 检查所有实例状态，总数: {len(all_instances)} (预期: {self.max_instances})")

            # 如果总实例数远低于预期，说明初始化失败或大量实例崩溃
            if len(all_instances) < self.max_instances * 0.5:  # 实例数少于预期的50%
                self.logger.error(
                    f"⚠️ 实例数严重不足! 当前: {len(all_instances)}, 预期: {self.max_instances}, "
                    f"缺口: {self.max_instances - len(all_instances)}. 这表明浏览器池初始化失败或大量实例崩溃!"
                )

                # 输出详细诊断信息
                for instance_id, instance in all_instances.items():
                    last_success = instance.get('last_success', 0)
                    status = instance.get('status', 'unknown')
                    total_requests = instance.get('total_requests', 0)
                    success_requests = instance.get('success_requests', 0)
                    time_since_success = time.time() - last_success if last_success > 0 else -1

                    self.logger.error(
                        f"实例 {instance_id} 诊断: 状态={status}, 总请求={total_requests}, "
                        f"成功={success_requests}, 最后成功={int(time_since_success)}秒前"
                    )

            # 找出所有不可用的实例
            problematic_instances = []
            for instance_id, instance in all_instances.items():
                status = instance.get('status', 'unknown')
                self.logger.debug(f"实例 {instance_id} 状态: {status}, 请求数: {instance.get('total_requests', 0)}")

                # 任何非active状态的实例都认为是问题实例
                if status != 'active':
                    problematic_instances.append(instance_id)
                    self.logger.warning(f"🚫 发现非活跃实例: {instance_id} (状态: {status})")
                    continue

                # 对于活跃实例，检查失败率
                recent_requests = instance.get('total_requests', 0)
                if recent_requests >= 5:  # 只有足够的请求数才判断失败率
                    recent_failures = len(instance.get('failures', []))
                    failure_rate = recent_failures / recent_requests

                    # 如果失败率超过30%（降低阈值），认为是问题实例
                    if failure_rate > 0.3:
                        problematic_instances.append(instance_id)
                        self.logger.warning(f"⚠️ 发现高失败率实例: {instance_id} (失败率: {failure_rate:.1%})")

            # 强制替换问题实例（最多3个，增加数量）
            if problematic_instances:
                self.logger.warning(f"🎯 发现 {len(problematic_instances)} 个问题实例，准备替换")

                for i, instance_id in enumerate(problematic_instances[:3]):
                    self.logger.warning(f"🔧 强制替换问题实例 {i+1}/3: {instance_id} (状态: {all_instances[instance_id].get('status', 'unknown')})")
                    self._schedule_replacement(instance_id, priority=1)  # 使用最高优先级
            else:
                # 如果实例数远低于预期但找不到明显的问题实例，使用强制替换
                if len(all_instances) < self.max_instances * 0.5:
                    self.logger.warning(f"🔴 实例数严重不足，使用强制替换策略")
                    # 随机替换一个活跃实例，使用强制模式
                    active_instances = [iid for iid, instance in all_instances.items()
                                     if instance.get('status') == 'active']
                    if active_instances:
                        target_id = active_instances[0]
                        self.logger.warning(f"⚡ 强制替换疑似卡住的活跃实例: {target_id}")
                        # 100ms后调用，传递force参数
                        if self._running:
                            # 使用默认参数捕获当前target_id值
                            threading.Timer(0.1, lambda tid=target_id: self._execute_replacement(
                                ReplacementTask(tid, time.time(), 1),
                                force=True
                            )).start()
                else:
                    self.logger.warning("🤔 未找到明显的问题实例，尝试随机替换一个活跃实例以恢复")
                    # 如果没有找到问题实例，随机替换一个活跃实例来强制刷新
                    active_instances = [iid for iid, instance in all_instances.items()
                                     if instance.get('status') == 'active']
                    if active_instances:
                        target_id = active_instances[0]
                        self.logger.warning(f"🎲 随机替换活跃实例以恢复: {target_id}")
                        self._schedule_replacement(target_id, priority=1)

        except Exception as e:
            self.logger.error(f"强制替换问题实例时出错: {e}")
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")

    def _replacement_worker(self):
        """替换工作线程"""
        self.logger.info("🔧 实例替换线程已启动")

        while self._running:
            try:
                # 等待替换任务，超时1秒以便检查停止信号
                try:
                    task = self._replacement_queue.get(timeout=1)
                except Empty:
                    continue

                # 执行替换
                self._execute_replacement(task)

                # 标记任务完成
                self._replacement_queue.task_done()

            except Exception as e:
                self.logger.error(f"替换线程出错: {e}")
                if not self._running:
                    break

        self.logger.info("🔧 实例替换线程已退出")

    def _execute_replacement(self, task: ReplacementTask, force: bool = False):
        """执行实例替换"""
        instance_id = task.failed_instance_id
        self.logger.info(f"🔄 开始替换实例: {instance_id} {'(强制模式)' if force else ''}")

        try:
            # 检查实例状态，确保确实需要替换
            if not self._should_replace_instance(instance_id, force=force):
                self.logger.debug(f"实例 {instance_id} 不需要替换，跳过")
                return

            # 执行替换
            if self.replacement_callback:
                self.stats['total_replacements'] += 1

                try:
                    new_instance_id = self.replacement_callback(instance_id)
                    if new_instance_id and new_instance_id != instance_id:
                        # 获取新代理（如果使用代理）
                        new_proxy = None
                        if self.proxy_manager:
                            try:
                                new_proxy = self.proxy_manager.get_random_proxy()
                                new_proxy = new_proxy.get('proxy') if new_proxy else None
                            except Exception as e:
                                self.logger.warning(f"获取新代理失败: {e}")

                        # 更新封禁检测器中的记录
                        self.ban_detector.mark_instance_replaced(instance_id, new_instance_id, new_proxy)

                        self.stats['successful_replacements'] += 1
                        self.stats['auto_replacements'] += 1

                        self.logger.info(
                            f"✅ 实例替换成功: {instance_id} -> {new_instance_id} "
                            f"(代理: {new_proxy or '直连'})"
                        )
                    else:
                        self.logger.warning(f"替换回调返回无效的新实例ID: {new_instance_id}")
                        self.stats['failed_replacements'] += 1

                except Exception as e:
                    self.logger.error(f"执行实例替换时出错: {e}")
                    self.stats['failed_replacements'] += 1

                    # 替换失败，5分钟后重试
                    if self._running:
                        threading.Timer(300, lambda: self._schedule_replacement(instance_id, priority=3)).start()

            else:
                self.logger.error("未设置替换回调函数，无法执行替换")
                self.stats['failed_replacements'] += 1

        except Exception as e:
            self.logger.error(f"执行替换任务时出错: {e}")
            self.stats['failed_replacements'] += 1

    def _should_replace_instance(self, instance_id: int, force: bool = False) -> bool:
        """检查是否应该替换实例"""
        # 检查是否被封禁
        if self.ban_detector.is_instance_banned(instance_id):
            return True

        # 检查实例是否存在
        if instance_id not in self.ban_detector.browser_instances:
            self.logger.warning(f"实例 {instance_id} 不存在于检测器中")
            return True

        # 检查实例是否卡住（新增逻辑）
        instance = self.ban_detector.browser_instances[instance_id]
        current_time = time.time()
        last_success = instance.get('last_success', 0)
        total_requests = instance.get('total_requests', 0)
        success_requests = instance.get('success_requests', 0)
        status = instance.get('status', 'unknown')

        # 如果是强制替换模式，直接返回True
        if force:
            return True

        # 检测卡住条件：
        # 1. 实例状态为active但长时间没有成功请求
        if status == 'active':
            # 如果距离最后成功超过5分钟，且总请求数>50但成功率极低，可能是卡住
            if current_time - last_success > 300:  # 5分钟无响应
                if total_requests > 50:
                    success_rate = success_requests / total_requests if total_requests > 0 else 0
                    if success_rate < 0.1:  # 成功率低于10%
                        self.logger.warning(
                            f"检测到卡住实例 {instance_id}: "
                            f"最后成功时间: {int(current_time - last_success)}秒前, "
                            f"总请求: {total_requests}, 成功率: {success_rate:.1%}"
                        )
                        return True

        return False

    def get_available_instance_id(self) -> Optional[int]:
        """获取可用的实例ID"""
        available_instances = self.ban_detector.get_available_instances()
        if available_instances:
            return available_instances[0]
        return None

    def get_status_report(self) -> str:
        """获取状态报告"""
        # 从封禁检测器获取详细报告
        ban_report = self.ban_detector.get_detailed_report()

        # 添加管理器特定信息
        manager_report = [
            "\n🔧 实例管理器状态:",
            f"  - 管理器状态: {'运行中' if self._running else '已停止'}",
            f"  - 总替换数: {self.stats['total_replacements']}",
            f"  - 成功替换: {self.stats['successful_replacements']}",
            f"  - 失败替换: {self.stats['failed_replacements']}",
            f"  - 手动替换: {self.stats['manual_replacements']}",
            f"  - 自动替换: {self.stats['auto_replacements']}",
            f"  - 等待替换队列: {self._replacement_queue.qsize()}"
        ]

        return ban_report + "\n" + "\n".join(manager_report)

    def _log_status_report(self):
        """记录状态报告"""
        report = self.get_status_report()
        for line in report.split('\n'):
            self.logger.info(line)