#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程锁管理器
用于防止同一时间运行多个爬虫实例
"""

import os
import sys
import time
import errno
import psutil
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class ProcessLock:
    """
    进程文件锁管理器
    使用fcntl实现跨进程的互斥锁
    """

    def __init__(self, lock_file_path: str = None, timeout: int = 3600):
        """
        初始化进程锁

        Args:
            lock_file_path: 锁文件路径
            timeout: 锁超时时间（秒），默认1小时
        """
        self.lock_file_path = lock_file_path or self._get_default_lock_file()
        self.timeout = timeout
        self.lock_file = None
        self.is_locked = False
        self.lock_time = None

    def _get_default_lock_file(self) -> str:
        """获取默认锁文件路径"""
        # 获取项目根目录
        project_root = Path(__file__).parent.parent
        lock_dir = project_root / "scheduler" / "locks"
        lock_dir.mkdir(exist_ok=True, parents=True)
        return str(lock_dir / "nga_spider.lock")

    def _read_lock_info(self) -> Optional[dict]:
        """读取锁文件信息"""
        try:
            if not os.path.exists(self.lock_file_path):
                return None

            with open(self.lock_file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            if not content:
                return None

            # 解析锁信息
            lines = content.split('\n')
            info = {}
            for line in lines:
                if '=' in line:
                    key, value = line.split('=', 1)
                    info[key.strip()] = value.strip()

            return info

        except Exception as e:
            logger.debug(f"读取锁文件失败: {e}")
            return None

    def _write_lock_info(self):
        """写入锁文件信息"""
        try:
            lock_info = f"pid={os.getpid()}\n"
            lock_info += f"start_time={datetime.now().isoformat()}\n"
            lock_info += f"script={sys.argv[0]}\n"

            with open(self.lock_file_path, 'w', encoding='utf-8') as f:
                f.write(lock_info)
                f.flush()
                os.fsync(f.fileno())

        except Exception as e:
            logger.error(f"写入锁文件失败: {e}")

    def _is_process_alive(self, pid: int) -> bool:
        """检查进程是否存活"""
        try:
            return psutil.pid_exists(pid)
        except Exception:
            # 如果psutil不可用，使用kill(0)检查
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def _is_lock_expired(self, lock_info: dict) -> bool:
        """检查锁是否过期"""
        try:
            start_time_str = lock_info.get('start_time')
            if not start_time_str:
                return True

            start_time = datetime.fromisoformat(start_time_str)
            now = datetime.now()

            return (now - start_time).total_seconds() > self.timeout

        except Exception as e:
            logger.debug(f"检查锁过期时间失败: {e}")
            return True  # 如果无法确定，认为已过期

    def _cleanup_stale_lock(self) -> bool:
        """清理过期的锁"""
        try:
            lock_info = self._read_lock_info()
            if not lock_info:
                return True

            pid_str = lock_info.get('pid')
            if not pid_str:
                return True

            pid = int(pid_str)

            # 检查进程是否还在运行
            if not self._is_process_alive(pid):
                logger.debug(f"检测到过期锁文件，进程 {pid} 已不存在")
                os.unlink(self.lock_file_path)
                return True

            # 检查锁是否超时
            if self._is_lock_expired(lock_info):
                logger.debug(f"检测到超时锁文件，进程 {pid} 运行时间超过 {self.timeout} 秒")

                # 尝试终止过期进程
                try:
                    process = psutil.Process(pid)
                    logger.warning(f"正在终止超时进程 {pid} ({process.name()})")

                    # 先尝试优雅终止
                    process.terminate()

                    # 等待5秒
                    time.sleep(5)

                    # 如果还在运行，强制杀死
                    if process.is_running():
                        logger.warning(f"进程 {pid} 未响应终止信号，强制杀死")
                        process.kill()

                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.debug(f"无法终止进程 {pid}: {e}")

                # 删除锁文件
                os.unlink(self.lock_file_path)
                return True

            return False  # 锁仍然有效

        except Exception as e:
            logger.error(f"清理过期锁失败: {e}")
            return False

    def acquire(self, blocking: bool = True, timeout: int = None) -> bool:
        """
        获取锁

        Args:
            blocking: 是否阻塞等待
            timeout: 阻塞等待的超时时间（秒）

        Returns:
            bool: 是否成功获取锁
        """
        if self.is_locked:
            logger.warning("锁已经被当前进程持有")
            return True

        wait_timeout = timeout or (self.timeout if blocking else 0)
        start_time = time.time()

        while True:
            # 尝试清理过期锁
            if not self._cleanup_stale_lock():
                # 锁仍然有效，检查是否需要等待
                if not blocking:
                    logger.debug("无法获取锁：其他实例正在运行")
                    return False

                # 检查等待超时
                if time.time() - start_time > wait_timeout:
                    logger.warning(f"获取锁超时（{wait_timeout}秒）")
                    return False

                # 等待一段时间后重试
                time.sleep(5)
                continue

            # 尝试创建锁文件并获取独占锁
            try:
                # 确保目录存在
                os.makedirs(os.path.dirname(self.lock_file_path), exist_ok=True)

                # 创建/打开锁文件
                self.lock_file = open(self.lock_file_path, 'w')

                # 尝试获取文件锁
                import fcntl
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                # 写入锁信息
                self._write_lock_info()

                self.is_locked = True
                self.lock_time = datetime.now()

                logger.debug(f"✅ 成功获取进程锁，PID: {os.getpid()}")
                return True

            except IOError as e:
                # 无法获取锁
                if self.lock_file:
                    self.lock_file.close()
                    self.lock_file = None

                if e.errno == errno.EAGAIN:
                    # 锁被其他进程持有
                    if not blocking:
                        logger.debug("无法获取锁：其他实例正在运行")
                        return False

                    # 检查等待超时
                    if time.time() - start_time > wait_timeout:
                        logger.warning(f"获取锁超时（{wait_timeout}秒）")
                        return False

                    time.sleep(5)
                    continue
                else:
                    logger.error(f"获取锁时发生错误: {e}")
                    return False

            except Exception as e:
                logger.error(f"获取锁时发生未知错误: {e}")
                if self.lock_file:
                    self.lock_file.close()
                    self.lock_file = None
                return False

    def release(self):
        """释放锁"""
        if not self.is_locked:
            logger.warning("尝试释放未被持有的锁")
            return

        try:
            if self.lock_file:
                import fcntl
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                self.lock_file = None

            # 删除锁文件
            if os.path.exists(self.lock_file_path):
                os.unlink(self.lock_file_path)

            self.is_locked = False
            lock_duration = datetime.now() - self.lock_time if self.lock_time else timedelta(0)
            logger.debug(f"✅ 成功释放进程锁，运行时长: {lock_duration}")

        except Exception as e:
            logger.error(f"释放锁时发生错误: {e}")

    def __enter__(self):
        """上下文管理器入口"""
        if not self.acquire():
            raise RuntimeError("无法获取进程锁")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.release()

    def __del__(self):
        """析构函数，确保锁被释放"""
        if self.is_locked:
            self.release()


def check_spider_running() -> bool:
    """
    检查是否有爬虫正在运行

    Returns:
        bool: True表示有爬虫正在运行
    """
    lock = ProcessLock()
    lock_info = lock._read_lock_info()

    if not lock_info:
        return False

    pid_str = lock_info.get('pid')
    if not pid_str:
        return False

    try:
        pid = int(pid_str)
        return lock._is_process_alive(pid)
    except ValueError:
        return False


def get_spider_status() -> dict:
    """
    获取当前爬虫运行状态

    Returns:
        dict: 包含爬虫状态信息的字典
    """
    lock = ProcessLock()
    lock_info = lock._read_lock_info()

    if not lock_info:
        return {
            'running': False,
            'pid': None,
            'start_time': None,
            'duration': None
        }

    try:
        pid = int(lock_info.get('pid', 0))
        start_time_str = lock_info.get('start_time')

        is_alive = lock._is_process_alive(pid)
        duration = None

        if is_alive and start_time_str:
            start_time = datetime.fromisoformat(start_time_str)
            duration = (datetime.now() - start_time).total_seconds()

        return {
            'running': is_alive,
            'pid': pid if is_alive else None,
            'start_time': start_time_str,
            'duration': duration
        }

    except (ValueError, TypeError):
        return {
            'running': False,
            'pid': None,
            'start_time': None,
            'duration': None
        }


if __name__ == "__main__":
    # 测试代码
    import argparse

    parser = argparse.ArgumentParser(description='进程锁测试工具')
    parser.add_argument('--check', action='store_true', help='检查爬虫状态')
    parser.add_argument('--test-lock', action='store_true', help='测试获取锁')

    args = parser.parse_args()

    if args.check:
        status = get_spider_status()
        print("爬虫状态:")
        for key, value in status.items():
            print(f"  {key}: {value}")

    elif args.test_lock:
        print("测试获取进程锁...")
        try:
            with ProcessLock() as lock:
                print("✅ 成功获取锁")
                print("按 Enter 释放锁...")
                input()
        except RuntimeError as e:
            print(f"❌ {e}")