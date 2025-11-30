#!/usr/bin/env python3
"""
资源监控脚本
监控CPU、内存和代理池状态
"""
import psutil
import time
import os
import sys
from datetime import datetime

def get_memory_usage():
    """获取内存使用率"""
    memory = psutil.virtual_memory()
    return {
        'total': memory.total / (1024**3),  # GB
        'used': memory.used / (1024**3),
        'free': memory.free / (1024**3),
        'percent': memory.percent
    }

def get_cpu_usage():
    """获取CPU使用率"""
    return psutil.cpu_percent(interval=1)

def get_chrome_processes():
    """获取Chrome相关进程"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_percent', 'cpu_percent']):
        try:
            if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'memory': proc.info['memory_percent'],
                    'cpu': proc.info['cpu_percent']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return processes

def check_database_lock(db_path='nga.db'):
    """检查数据库是否被锁定"""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path, timeout=1)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        return False
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            return True
    except:
        pass
    return False

def monitor_resources(duration=60, interval=5):
    """
    监控系统资源

    Args:
        duration: 监控总时长（秒）
        interval: 检查间隔（秒）
    """
    print("=" * 80)
    print("🔍 系统资源监控启动")
    print("=" * 80)
    print(f"监控时长: {duration}秒，检查间隔: {interval}秒\n")

    start_time = time.time()
    max_memory = 0
    max_cpu = 0
    chrome_count = 0
    max_chrome_count = 0
    db_lock_count = 0

    check_count = 0
    while time.time() - start_time < duration:
        check_count += 1

        # 获取内存信息
        memory = get_memory_usage()
        max_memory = max(max_memory, memory['percent'])

        # 获取CPU信息
        cpu = get_cpu_usage()
        max_cpu = max(max_cpu, cpu)

        # 获取Chrome进程
        chrome_procs = get_chrome_processes()
        chrome_count = len(chrome_procs)
        max_chrome_count = max(max_chrome_count, chrome_count)

        # 检查数据库锁
        is_locked = check_database_lock()
        if is_locked:
            db_lock_count += 1

        # 输出当前状态
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] 检查 #{check_count}")
        print(f"  内存: {memory['percent']:.1f}% ({memory['used']:.1f}/{memory['total']:.1f}GB)")
        print(f"  CPU: {cpu:.1f}%")
        print(f"  Chrome进程: {chrome_count}个")
        if chrome_procs:
            for proc in chrome_procs[:3]:  # 只显示前3个
                print(f"    - PID {proc['pid']}: {proc['memory']:.1f}%内存, {proc['cpu']:.1f}%CPU")
        if is_locked:
            print("  ⚠️  数据库被锁定！")
        print()

        time.sleep(interval)

    # 输出统计报告
    print("=" * 80)
    print("📊 监控统计报告")
    print("=" * 80)
    print(f"监控次数: {check_count}")
    print(f"最大内存使用率: {max_memory:.1f}%")
    print(f"最大CPU使用率: {max_cpu:.1f}%")
    print(f"最大Chrome进程数: {max_chrome_count}个")
    print(f"数据库锁定次数: {db_lock_count}")

    # 给出建议
    print("\n💡 优化建议:")
    if max_memory > 80:
        print("  ❌ 内存使用率过高 (>80%)")
        print("     建议: 降低 PLAYWRIGHT_POOL_SIZE 到 1 或 2")
    elif max_memory > 60:
        print("  ⚠️  内存使用率较高 (>60%)")
        print("     建议: 保持当前配置，密切监控")
    else:
        print("  ✅ 内存使用率正常")

    if max_cpu > 90:
        print("  ❌ CPU使用率过高 (>90%)")
        print("     建议: 降低并发数 (CONCURRENT_REQUESTS)")
    elif max_cpu > 70:
        print("  ⚠️  CPU使用率较高 (>70%)")
        print("     建议: 适当降低并发数")

    if max_chrome_count > 5:
        print("  ❌ 浏览器进程过多 (>5)")
        print("     建议: 检查是否有僵尸进程未正确关闭")

    if db_lock_count > 0:
        print("  ⚠️  数据库锁定")
        print("     建议: 检查并发写入，考虑使用PostgreSQL")

    print("=" * 80)

if __name__ == '__main__':
    # 检查依赖
    try:
        import psutil
    except ImportError:
        print("❌ 缺少依赖: psutil")
        print("请运行: pip install psutil")
        sys.exit(1)

    # 运行监控
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    monitor_resources(duration, interval)
