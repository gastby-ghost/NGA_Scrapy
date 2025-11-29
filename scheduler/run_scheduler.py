import subprocess
import time
import signal
import sys
import logging
import yaml
import os
from datetime import datetime, timedelta
from collections import deque
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from pytz import timezone

# 获取项目根目录（scheduler 的父目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# 导入邮件通知模块
try:
    from email_notifier import EmailNotifier, StatisticsCollector
except ImportError:
    logger = logging.getLogger(__name__)
    logger.error("无法导入 email_notifier 模块，请确保文件存在")
    sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scheduler.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# 全局变量
spider_process = None
shutdown_requested = False
email_notifier = None
stats_collector = None
consecutive_failures = 0
error_rates = deque(maxlen=100)  # 保存最近100次执行的错误率
spider_start_time = None
first_run_completed = False  # 标记是否已完成第一次爬虫

# 加载配置文件
def load_config():
    """加载邮件配置文件"""
    global email_notifier, stats_collector

    config_file = os.path.join(os.path.dirname(__file__), 'email_config.yaml')

    if not os.path.exists(config_file):
        logger.warning(f"邮件配置文件不存在: {config_file}")
        logger.info("请复制 email_config.yaml 并配置你的邮箱信息")
        return None

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 创建邮件发送器
        if config.get('notifications', {}).get('enable_statistics_report') or \
           config.get('notifications', {}).get('enable_error_alerts'):

            email_notifier = EmailNotifier(
                smtp_server=config['smtp_server'],
                smtp_port=config['smtp_port'],
                username=config['username'],
                password=config['password'],
                from_email=config['from_email'],
                to_emails=config['to_emails'],
                use_tls=config.get('use_tls', True)
            )
            logger.info("邮件通知器初始化成功")

        # 创建统计收集器
        stats_collector = StatisticsCollector()
        logger.info("统计收集器初始化成功")

        return config

    except Exception as e:
        logger.exception(f"加载配置文件时发生错误: {e}")
        return None

def signal_handler(signum, frame):
    """信号处理器：优雅关闭调度器和子进程"""
    global shutdown_requested
    logger.info(f"收到信号 {signum}，开始优雅关闭...")
    shutdown_requested = True

    # 终止爬虫子进程
    if spider_process and spider_process.poll() is None:
        logger.info("正在终止爬虫子进程...")
        spider_process.terminate()

        # 等待进程结束，最多等待10秒
        try:
            spider_process.wait(timeout=10)
            logger.info("爬虫子进程已终止")
        except subprocess.TimeoutExpired:
            logger.warning("爬虫子进程未在10秒内终止，强制杀死")
            spider_process.kill()
            spider_process.wait()

    # 关闭调度器
    scheduler.shutdown(wait=False)
    logger.info("调度器已关闭")
    sys.exit(0)

def run_spider():
    """执行爬虫任务，带重试机制和状态监控"""
    global spider_process, consecutive_failures, spider_start_time, error_rates, first_run_completed

    # 检查是否有关闭请求
    if shutdown_requested:
        logger.info("跳过爬虫执行（已请求关闭）")
        return

    # 检查是否有正在运行的爬虫进程
    if spider_process and spider_process.poll() is None:
        logger.warning("检测到爬虫仍在运行，跳过本次执行")
        return

    spider_start_time = datetime.now()
    execution_success = False
    error_output = []
    spider_stats = None

    try:
        logger.info("=" * 60)
        logger.info(f"开始执行爬虫任务 - {datetime.now()}")
        logger.info("=" * 60)

        # 使用Popen代替run()，避免阻塞
        spider_process = subprocess.Popen(
            ["scrapy", "crawl", "nga"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # 实时输出爬虫日志
        logger.info(f"爬虫进程已启动，PID: {spider_process.pid}")

        # 等待进程完成并记录输出，同时解析统计信息
        output_lines = []
        stats_dict_str = ""  # 用于累积统计字典的字符串
        in_stats_section = False  # 是否在统计字典部分

        for line in spider_process.stdout:
            line_stripped = line.strip()
            output_lines.append(line_stripped)

            if line_stripped:
                logger.info(f"[Spider] {line_stripped}")

            # 检测统计信息部分的开始
            if "Dumping Scrapy stats:" in line_stripped:
                in_stats_section = True
                continue

            # 如果在统计部分，累积字典字符串
            if in_stats_section:
                stats_dict_str += line_stripped

                # 如果遇到完整的字典（以}结尾），尝试解析
                if line_stripped.endswith("}"):
                    try:
                        import ast
                        spider_stats = ast.literal_eval(stats_dict_str)
                        logger.info(f"✅ 成功解析爬虫统计信息:")
                        logger.info(f"   - 抓取项目数: {spider_stats.get('item_scraped_count', 0)}")
                        logger.info(f"   - 下载页面数: {spider_stats.get('downloader/response_count', 0)}")
                        logger.info(f"   - 运行时间: {spider_stats.get('elapsed_time_seconds', 0):.2f}秒")
                        logger.info(f"   - 完成状态: {spider_stats.get('finish_reason', 'unknown')}")
                    except (ValueError, SyntaxError) as e:
                        logger.warning(f"⚠️ 统计信息解析失败: {e}")
                        logger.debug(f"原始数据: {stats_dict_str}")

                    # 重置状态
                    in_stats_section = False
                    stats_dict_str = ""

        # 等待进程结束
        return_code = spider_process.wait()

        if return_code == 0:
            logger.info("=" * 60)
            logger.info(f"爬虫任务执行成功 - {datetime.now()}")
            logger.info("=" * 60)
            execution_success = True
            consecutive_failures = 0  # 重置连续失败计数

            # 如果是第一次成功执行，发送统计报告
            if not first_run_completed:
                logger.info("第一次爬虫执行成功，开始发送统计报告...")
                send_statistics_report()
                first_run_completed = True
        else:
            logger.error(f"爬虫任务执行失败，返回码: {return_code}")
            consecutive_failures += 1
            error_output = output_lines[-20:]  # 保存最后20行输出作为错误信息

            if output_lines:
                logger.error("最后输出:")
                for line in output_lines[-10:]:
                    logger.error(f"  {line}")

        spider_process = None

        # 尝试从日志文件中获取统计信息（更可靠的方法）
        if not spider_stats:
            spider_stats = _parse_stats_from_log()
            if spider_stats:
                logger.info(f"✅ 从日志文件中成功解析爬虫统计信息:")
                logger.info(f"   - 抓取项目数: {spider_stats.get('item_scraped_count', 0)}")
                logger.info(f"   - 下载页面数: {spider_stats.get('downloader/response_count', 0)}")
                logger.info(f"   - 运行时间: {spider_stats.get('elapsed_time_seconds', 0):.2f}秒")
                logger.info(f"   - 完成状态: {spider_stats.get('finish_reason', 'unknown')}")

        # 保存统计信息到文件
        if spider_stats:
            _save_spider_statistics(spider_stats, return_code, execution_success)
        else:
            logger.warning("⚠️ 未获取到爬虫统计信息")

        # 计算错误率（简化计算：基于返回码）
        error_rate = 0 if return_code == 0 else 100
        error_rates.append(error_rate)

        # 检查错误告警条件
        check_error_alerts(return_code, error_output)

    except Exception as e:
        logger.exception(f"执行爬虫任务时发生错误: {e}")
        consecutive_failures += 1
        error_output = [str(e)]
        spider_process = None

        # 记录错误率
        error_rates.append(100)

        # 检查错误告警条件
        check_error_alerts(-1, error_output)


def _parse_stats_from_log():
    """从日志文件中解析最新的爬虫统计信息"""
    try:
        import re
        import ast

        log_file = os.path.join(PROJECT_ROOT, "nga_spider.log")
        if not os.path.exists(log_file):
            logger.debug(f"日志文件不存在: {log_file}")
            return None

        # 读取日志文件的最后200行（避免读取整个大文件）
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 寻找最后的 "Dumping Scrapy stats:" 行
        stats_line_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if "Dumping Scrapy stats:" in lines[i]:
                stats_line_idx = i
                break

        if stats_line_idx is None:
            logger.debug("未找到统计信息行")
            return None

        # 收集从统计行开始的所有行，直到遇到空行或非字典格式
        stats_lines = []
        for i in range(stats_line_idx, len(lines)):
            line = lines[i].strip()
            if not line:
                break
            stats_lines.append(line)

        # 合并所有行
        stats_text = " ".join(stats_lines)

        # 提取字典部分（寻找以 { 开始以 } 结束的部分）
        # 使用正则表达式匹配完整的字典
        dict_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
        match = re.search(dict_pattern, stats_text)

        if match:
            stats_dict_str = match.group(0)
            try:
                # 清理字符串，替换 Python 特定的类型标记
                stats_dict_str = stats_dict_str.replace("datetime.datetime", "")
                stats_dict_str = stats_dict_str.replace("datetime.timezone", "")
                stats_dict_str = re.sub(r"tzinfo=[^,)]*", "", stats_dict_str)

                # 尝试解析
                stats_dict = ast.literal_eval(stats_dict_str)
                logger.debug(f"✅ 成功从日志解析统计信息")
                return stats_dict
            except (ValueError, SyntaxError) as e:
                logger.debug(f"⚠️ 统计信息解析失败: {e}")
                logger.debug(f"原始数据: {stats_dict_str[:200]}")
                return None
        else:
            logger.debug("未找到统计字典格式")
            return None

    except Exception as e:
        logger.debug(f"解析日志文件时发生错误: {e}")
        return None

def _save_spider_statistics(stats: dict, return_code: int, success: bool):
    """保存爬虫统计信息到文件"""
    try:
        import os
        import json
        from datetime import datetime

        # 创建统计目录
        stats_dir = os.path.join(SCRIPT_DIR, "stats")
        os.makedirs(stats_dir, exist_ok=True)

        # 生成文件名（包含时间戳）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        stats_file = os.path.join(stats_dir, f"spider_stats_{timestamp}.json")

        # 准备要保存的数据
        stats_data = {
            'timestamp': datetime.now().isoformat(),
            'return_code': return_code,
            'success': success,
            'spider_stats': stats,
            'summary': {
                'items_scraped': stats.get('item_scraped_count', 0),
                'pages_crawled': stats.get('downloader/response_count', 0),
                'runtime_seconds': stats.get('elapsed_time_seconds', 0),
                'response_bytes': stats.get('downloader/response_bytes', 0),
                'finish_reason': stats.get('finish_reason', 'unknown'),
                'success_rate': 100.0 if success else 0.0,
            }
        }

        # 保存到文件
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats_data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ 统计信息已保存到: {stats_file}")

    except Exception as e:
        logger.exception(f"❌ 保存统计信息失败: {e}")

def check_error_alerts(return_code: int, error_output: list):
    """检查是否需要发送错误告警"""
    config = scheduler.config if hasattr(scheduler, 'config') else None

    if not config or not config.get('notifications', {}).get('enable_error_alerts', False):
        return

    notifications_config = config['notifications']

    # 检查连续失败次数
    threshold = notifications_config.get('consecutive_failures_threshold', 3)
    if consecutive_failures >= threshold:
        message = f"爬虫连续失败 {consecutive_failures} 次"
        details = "\n".join(error_output) if error_output else "无详细错误信息"

        logger.error(f"发送告警邮件: {message}")
        if email_notifier:
            email_notifier.send_alert("爬虫连续失败", message, details)

    # 检查超时
    if spider_start_time:
        timeout_minutes = notifications_config.get('spider_timeout_minutes', 60)
        if (datetime.now() - spider_start_time).total_seconds() > timeout_minutes * 60:
            message = f"爬虫运行时间超过 {timeout_minutes} 分钟"
            details = f"开始时间: {spider_start_time}"

            logger.error(f"发送告警邮件: {message}")
            if email_notifier:
                email_notifier.send_alert("爬虫运行超时", message, details)

    # 检查错误率
    error_rate_config = notifications_config.get('error_rate_alert', {})
    if error_rate_config.get('enabled', False) and error_rates:
        # 计算最近N次执行的平均错误率
        recent_rates = list(error_rates)
        avg_error_rate = sum(recent_rates) / len(recent_rates)
        threshold_percent = error_rate_config.get('threshold_percent', 20)

        if avg_error_rate >= threshold_percent:
            message = f"爬虫错误率达到 {avg_error_rate:.1f}%，超过阈值 {threshold_percent}%"
            details = f"最近 {len(recent_rates)} 次执行的平均错误率: {avg_error_rate:.2f}%"

            logger.error(f"发送告警邮件: {message}")
            if email_notifier:
                email_notifier.send_alert("爬虫错误率过高", message, details)

def send_statistics_report():
    """发送统计报告"""
    global stats_collector

    if not email_notifier or not stats_collector:
        logger.warning("邮件通知器或统计收集器未初始化，跳过统计报告")
        return

    config = scheduler.config if hasattr(scheduler, 'config') else None
    if not config or not config.get('notifications', {}).get('enable_statistics_report', False):
        return

    try:
        logger.info("开始生成统计报告...")

        # 获取最近3天的统计数据
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)

        stats = stats_collector.collect_statistics(start_date, end_date)

        if not stats:
            logger.warning("未能收集到统计数据")
            return

        # 发送邮件
        success = email_notifier.send_statistics_report(stats)

        if success:
            logger.info("统计报告已发送")
        else:
            logger.error("发送统计报告失败")

    except Exception as e:
        logger.exception(f"发送统计报告时发生错误: {e}")

def job_listener(event):
    """监听任务执行事件"""
    if hasattr(event, 'exception') and event.exception:
        logger.error(f"任务执行异常: {event.exception}")
    else:
        logger.info(f"任务执行成功: {event.job_id}")

if __name__ == '__main__':
    # 启动时清空日志文件
    log_file = os.path.join(os.path.dirname(__file__), 'scheduler.log')
    if os.path.exists(log_file):
        open(log_file, 'w', encoding='utf-8').close()
        print(f"已清空日志文件: {log_file}")

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 加载配置
    config = load_config()

    # 显示启动信息
    logger.info("=" * 60)
    logger.info("NGA 爬虫调度器启动")
    logger.info("=" * 60)
    logger.info("配置信息:")
    logger.info("  - 时区: Asia/Shanghai")
    logger.info("  - 执行间隔: 30 分钟")
    logger.info("  - 启动时间: {}".format(datetime.now()))
    logger.info("  - 日志文件: scheduler.log")

    if config:
        logger.info("  - 邮件通知: 已启用")
        logger.info("  - 统计报告: {}".format(
            "启用" if config.get('notifications', {}).get('enable_statistics_report') else "禁用"
        ))
        if config.get('notifications', {}).get('enable_statistics_report'):
            logger.info("  - 首次统计报告: 将在第一次爬虫成功后发送")
        logger.info("  - 错误告警: {}".format(
            "启用" if config.get('notifications', {}).get('enable_error_alerts') else "禁用"
        ))
    else:
        logger.info("  - 邮件通知: 未配置")

    logger.info("=" * 60)
    logger.info("按 Ctrl+C 优雅退出")
    logger.info("=" * 60)

    # 创建调度器
    tz = timezone('Asia/Shanghai')
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.config = config  # 将配置附加到调度器对象

    # 添加爬虫任务
    scheduler.add_job(
        run_spider,
        'interval',
        minutes=30,
        id='nga_spider_job',
        next_run_time=datetime.now(tz),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300
    )

    # 添加统计报告任务（如果启用）
    if config and config.get('notifications', {}).get('enable_statistics_report', False):
        interval_days = config.get('notifications', {}).get('statistics_report_interval_days', 3)
        report_time = config.get('notifications', {}).get('statistics_report_time', '09:00')

        # 解析时间
        hour, minute = map(int, report_time.split(':'))

        scheduler.add_job(
            send_statistics_report,
            'cron',
            hour=hour,
            minute=minute,
            id='statistics_report_job',
            day_of_week='*/{}'.format(interval_days),  # 每3天执行一次
            timezone=tz
        )
        logger.info(f"统计报告任务已添加: 每 {interval_days} 天执行一次，时间: {report_time}")
        logger.info("首次统计报告将在第一次爬虫成功后自动发送")

    # 添加任务监听器
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # 启动调度器
    scheduler.start()

    # 主循环
    try:
        while True:
            if not shutdown_requested:
                jobs = scheduler.get_jobs()
                next_run = None
                for job in jobs:
                    if job.id == 'nga_spider_job':
                        next_run = job.next_run_time
                        break

                if spider_process and spider_process.poll() is None:
                    logger.debug(f"调度器运行中 | 爬虫PID: {spider_process.pid} | 下次执行: {next_run}")
                else:
                    logger.debug(f"调度器运行中 | 下次执行: {next_run}")

            time.sleep(30)

    except KeyboardInterrupt:
        logger.info("收到键盘中断信号")
        signal_handler(signal.SIGINT, None)
