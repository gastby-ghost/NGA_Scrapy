import subprocess
import time
import signal
import sys
import logging
import logging.handlers
import yaml
import os
import json
import glob
import threading
from datetime import datetime, timedelta
from collections import deque
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from pytz import timezone

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入进程锁模块
try:
    from NGA_Scrapy.utils.process_lock import ProcessLock, get_spider_status
except ImportError:
    logger = logging.getLogger(__name__)
    logger.error("无法导入 process_lock 模块")
    sys.exit(1)

# 获取项目根目录（scheduler 的父目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# 导入邮件通知模块
try:
    from email_notifier import EmailNotifier, StatisticsCollector
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("无法导入 email_notifier 模块，邮件通知功能将不可用")
    # 创建空的类以避免导入错误
    class EmailNotifier:
        def __init__(self, **kwargs):
            pass
        def send_alert(self, title, message, details=None):
            pass
        def send_statistics_report(self, stats):
            return False

    class StatisticsCollector:
        def collect_statistics(self, start_date, end_date):
            return None

# 配置日志（2026-10-13 长跑优化：文件轮转、仅文件 handler——nohup 下 stdout 无人看且会与文件
# 重复记录；早期崩溃输出由启动脚本重定向到 scheduler.stdout.log）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.handlers.RotatingFileHandler('scheduler.log', maxBytes=20 * 1024 * 1024, backupCount=3),
    ]
)

logger = logging.getLogger(__name__)

# 全局变量
spider_process = None
process_lock = None
shutdown_requested = False
email_notifier = None
stats_collector = None
consecutive_failures = 0
error_rates = deque(maxlen=100)  # 保存最近100次执行的错误率
spider_start_time = None
first_run_completed = False  # 标记是否已完成第一次爬虫
_last_alert_time = {}  # 告警类型 → 上次发送时间（同类告警冷却去重，2026-10-18）

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

        # 创建邮件发送器（任一通知开关打开即初始化）
        notifications = config.get('notifications', {})
        if (notifications.get('enable_statistics_report') or
                notifications.get('enable_error_alerts') or
                notifications.get('antibot_alert', {}).get('enabled') or
                notifications.get('item_drop_alert', {}).get('enabled')):

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
    global shutdown_requested, process_lock
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

    # 释放进程锁
    if process_lock:
        try:
            logger.info("正在释放进程锁...")
            process_lock.release()
            logger.info("✅ 进程锁已释放")
        except Exception as e:
            logger.error(f"释放进程锁时出错: {e}")

    # 关闭调度器
    scheduler.shutdown(wait=False)
    logger.info("调度器已关闭")
    sys.exit(0)

def run_spider():
    """执行爬虫任务，带重试机制和状态监控"""
    global spider_process, process_lock, consecutive_failures, spider_start_time, error_rates, first_run_completed

    # 检查是否有关闭请求
    if shutdown_requested:
        logger.info("跳过爬虫执行（已请求关闭）")
        return

    # 检查进程锁，防止并发运行
    spider_status = get_spider_status()
    if spider_status['running']:
        duration = spider_status.get('duration', 0)
        pid = spider_status.get('pid')
        logger.warning(f"检测到爬虫实例正在运行 (PID: {pid}, 运行时长: {duration:.1f}秒)，跳过本次执行")
        return

    # 检查当前进程管理的爬虫是否还在运行
    if spider_process and spider_process.poll() is None:
        logger.warning(f"当前调度的爬虫仍在运行 (PID: {spider_process.pid})，跳过本次执行")
        return

    spider_start_time = datetime.now()
    execution_success = False
    error_output = []
    spider_stats = None

    try:
        logger.info("=" * 60)
        logger.info(f"开始执行爬虫任务 - {datetime.now()}")
        logger.info("=" * 60)

        # 获取进程锁
        lock_timeout = 7200  # 2小时超时
        process_lock = ProcessLock(timeout=lock_timeout)

        if not process_lock.acquire(blocking=False):
            logger.error("无法获取进程锁，可能有其他爬虫实例正在运行")
            consecutive_failures += 1
            check_error_alerts(-1, ["无法获取进程锁"])
            return

        logger.info("✅ 成功获取进程锁，开始启动爬虫")

        # 使用Popen代替run()，避免阻塞
        # 使用settings_cloud配置（云服务器优化参数）
        spider_process = subprocess.Popen(
            ["scrapy", "crawl", "nga", "-s", "SETTINGS_MODULE=settings_cloud"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # 实时输出爬虫日志
        logger.info(f"爬虫进程已启动，PID: {spider_process.pid}")

        # 关闭看门狗（2026-10-18）：Scrapy 2.19 下 spider 已完成关闭后进程仍可能不退出
        # （Playwright/Twisted 收尾残留），wait() 无超时会让调度器永远阻塞。
        # 注意 Scrapy 的日志写在 LOG_FILE（nga_spider.log），不经 stdout——监控增量内容。
        # 出现 "Spider closed" 后给 90 秒退出宽限；整轮上限 2 小时。
        def _spider_watchdog():
            log_path = os.path.join(PROJECT_ROOT, 'nga_spider.log')
            try:
                pos = os.path.getsize(log_path)
            except OSError:
                pos = 0
            closed_at = None
            deadline = time.monotonic() + 7200
            while time.monotonic() < deadline:
                if spider_process.poll() is not None:
                    return
                try:
                    size = os.path.getsize(log_path)
                    if size < pos:  # 日志被轮转或重建
                        pos = 0
                    if size > pos:
                        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                            f.seek(pos)
                            chunk = f.read()
                        pos = size
                        if 'Spider closed' in chunk and closed_at is None:
                            closed_at = time.monotonic()
                except OSError:
                    pass

                if closed_at is not None and time.monotonic() - closed_at > 90:
                    logger.warning("spider 已关闭但进程 90 秒未退出，强制终止（关闭阶段残留）")
                    try:
                        spider_process.kill()
                    except Exception:
                        pass
                    return
                time.sleep(5)

            if spider_process.poll() is None:
                logger.warning("spider 运行超过 2 小时，强制终止")
                try:
                    spider_process.kill()
                except Exception:
                    pass

        threading.Thread(target=_spider_watchdog, daemon=True).start()

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
        else:
            logger.error(f"爬虫任务执行失败，返回码: {return_code}")
            consecutive_failures += 1
            error_output = output_lines[-20:]  # 保存最后20行输出作为错误信息

            if output_lines:
                logger.error("最后输出:")
                for line in output_lines[-10:]:
                    logger.error(f"  {line}")

        spider_process = None

        # 释放进程锁
        if process_lock:
            process_lock.release()
            process_lock = None
            logger.info("✅ 进程锁已释放")

        # 尝试从日志文件中获取统计信息（更可靠的方法）
        if not spider_stats:
            spider_stats = _parse_stats_from_log()
            if spider_stats:
                logger.info(f"✅ 从日志文件中成功解析爬虫统计信息:")
                logger.info(f"   - 抓取项目数: {spider_stats.get('item_scraped_count', 0)}")
                logger.info(f"   - 下载页面数: {spider_stats.get('downloader/response_count', 0)}")
                logger.info(f"   - 运行时间: {spider_stats.get('elapsed_time_seconds', 0):.2f}秒")
                logger.info(f"   - 完成状态: {spider_stats.get('finish_reason', 'unknown')}")

        # 结果信号告警（反爬/登录墙、抓取量骤降）
        # 必须在保存本轮统计前读取上一轮基线，否则会拿本轮和自己比
        if spider_stats:
            # 反爬命中数写入本轮统计，供统计报告汇总
            spider_stats['custom/antibot_hits'] = sum(
                1 for line in output_lines if '检测到反爬虫或验证页面' in line)
            check_result_alerts(spider_stats, output_lines, _load_prev_item_count())

        # 数据停滞检查（2026-10-18）：不管本轮是否"成功"，库里没新数据就告警
        check_data_freshness()

        # 保存统计信息到文件
        if spider_stats:
            _save_spider_statistics(spider_stats, return_code, execution_success)
        else:
            logger.warning("⚠️ 未获取到爬虫统计信息")

        # 首次成功：等本轮统计落盘后再发报告，避免报告窗口里少了本轮（2026-10-18）
        if return_code == 0 and not first_run_completed:
            logger.info("第一次爬虫执行成功，开始发送统计报告...")
            send_statistics_report()
            first_run_completed = True

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

        # 确保释放进程锁
        if process_lock:
            try:
                process_lock.release()
                logger.info("✅ 异常情况下已释放进程锁")
            except Exception as lock_error:
                logger.error(f"释放进程锁时出错: {lock_error}")
            finally:
                process_lock = None

        # 记录错误率
        error_rates.append(100)

        # 检查错误告警条件
        check_error_alerts(-1, error_output)


def run_monitors_job():
    """多平台监测轮（HN / Discourse + NGA→post 同步）。

    独立子进程执行，与 NGA spider 错峰注册（省性能）。若 NGA spider 正在跑则**等待其结束**
    （最多 10 分钟）再执行——2026-10-14 修正：原先「跳过」策略在 spider 轮变长（>3 分钟）时
    会连续空转、监测轮永远饿死；等待语义保证每 30 分钟必定成轮，仅在 spider 异常长跑时才放弃。
    监测轮本身对目标论坛低影响：请求节流 + 每轮预算，详见 monitors/config.yaml。
    """
    if shutdown_requested:
        logger.info("跳过监测轮（已请求关闭）")
        return
    wait_start = time.monotonic()
    logged_wait = False
    while spider_process and spider_process.poll() is None:
        if time.monotonic() - wait_start > 600:
            logger.warning("等待 NGA spider 超过 10 分钟仍未结束，本轮多平台监测放弃（下轮再来）")
            return
        if not logged_wait:
            logger.info("NGA spider 正在运行，等待其结束后执行监测轮（最多 10 分钟）…")
            logged_wait = True
        time.sleep(15)
    try:
        logger.info("=" * 60)
        logger.info(f"开始执行多平台监测轮 - {datetime.now()}")
        proc = subprocess.Popen(
            [os.path.join(PROJECT_ROOT, 'venv', 'bin', 'python'), 'monitors/run.py'],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line_stripped = line.strip()
            if line_stripped:
                logger.info(f"[Monitors] {line_stripped}")
        return_code = proc.wait()
        logger.info(f"多平台监测轮结束，返回码: {return_code}")
    except Exception:
        logger.exception("多平台监测轮执行失败")


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

# ========== 结果信号告警（2026-10-18） ==========
# 进程返回码只能说明「爬虫有没有跑完」，不能说明「有没有真的抓到东西」。
# 登录失效时进程正常退出、日志只有一行 warning——这里把结果信号也接进邮件告警。

def _send_alert_throttled(alert_type: str, message: str, details: str = None,
                          cooldown_minutes: int = 360) -> bool:
    """发送告警邮件；同类告警在冷却期内只发一次，避免 30 分钟一轮刷屏。"""
    now = datetime.now()
    last = _last_alert_time.get(alert_type)
    if last and (now - last).total_seconds() < cooldown_minutes * 60:
        logger.info(f"告警「{alert_type}」处于冷却期（{cooldown_minutes} 分钟），跳过发送")
        return False
    if not email_notifier:
        logger.warning(f"邮件通知器未初始化，无法发送告警: {message}")
        return False
    logger.warning(f"发送告警邮件: {message}")
    if email_notifier.send_alert(alert_type, message, details):
        _last_alert_time[alert_type] = now
        return True
    return False


def _load_prev_item_count():
    """读取上一轮爬虫的 item 数（stats 目录里最新的文件）。"""
    try:
        stats_dir = os.path.join(SCRIPT_DIR, 'stats')
        files = sorted(glob.glob(os.path.join(stats_dir, 'spider_stats_*.json')))
        if not files:
            return None
        with open(files[-1], 'r', encoding='utf-8') as f:
            data = json.load(f)
        return (data.get('summary', {}).get('items_scraped') or
                data.get('spider_stats', {}).get('item_scraped_count'))
    except Exception as e:
        logger.debug(f"读取上一轮统计失败: {e}")
        return None


def collect_db_metrics():
    """直接从数据库与磁盘采集研究数据状态（2026-10-18）。

    统计报告的核心问题：Scrapy 的 item_scraped_count 含大量重复抓取，
    不能代表入库增长。这里直接查库，给出真实的累计量与每日新增。
    """
    metrics = {}
    try:
        from database_config import get_database_url
        from sqlalchemy import create_engine, text

        engine = create_engine(get_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            for label, table in (('topic', 'topic'), ('reply', 'reply'),
                                 ('user', '"user"'), ('post', 'post')):
                metrics[f'db_{label}_total'] = conn.execute(
                    text(f'SELECT count(*) FROM {table}')).scalar()

            # 近 7 天每日入库（补齐缺失日期为 0，图表才能显示"哪天断了"）
            start_dt = datetime.now() - timedelta(days=6)
            start = start_dt.strftime('%Y-%m-%d')
            rows = conn.execute(
                text("""
                    SELECT left(sampling_time, 10) AS d, count(*)
                    FROM reply
                    WHERE left(sampling_time, 10) >= :start
                    GROUP BY 1 ORDER BY 1
                """), {'start': start}).fetchall()
            daily_map = {r[0]: r[1] for r in rows}
            days = [(start_dt + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
            metrics['db_daily_replies'] = {d: daily_map.get(d, 0) for d in days}

            latest = conn.execute(
                text('SELECT max(sampling_time) FROM reply')).scalar()
            metrics['db_latest_sampling'] = latest
            if latest:
                try:
                    latest_dt = datetime.strptime(latest, '%Y-%m-%d-%H-%M-%S')
                    metrics['db_latest_age_hours'] = round(
                        (datetime.now() - latest_dt).total_seconds() / 3600, 1)
                except ValueError:
                    pass
            metrics['db_size_pretty'] = conn.execute(
                text('SELECT pg_size_pretty(pg_database_size(current_database()))')).scalar()
    except Exception as e:
        logger.warning(f"采集数据库指标失败（报告将缺少入库数据）: {e}")

    try:
        store = os.path.join(PROJECT_ROOT, 'download_images')
        total = files = 0
        for root, _, names in os.walk(store):
            for name in names:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                    files += 1
                except OSError:
                    pass
        metrics['images_files'] = files
        metrics['images_size_mb'] = round(total / 1048576, 1)
    except Exception as e:
        logger.debug(f"采集图片目录失败: {e}")

    return metrics


def check_data_freshness():
    """数据停滞检测：最新采样时间距今超过阈值即告警（2026-10-18）。

    这是最直接的失败信号：不管进程为什么正常退出，只要库里没有新数据，
    说明采集实际上已经停了。
    """
    config = scheduler.config if hasattr(scheduler, 'config') else None
    if not config or not email_notifier:
        return
    cfg = config.get('notifications', {}).get('data_freshness_alert', {})
    if not cfg.get('enabled', True):
        return
    try:
        from database_config import get_database_url
        from sqlalchemy import create_engine, text

        engine = create_engine(get_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            latest = conn.execute(text('SELECT max(sampling_time) FROM reply')).scalar()
        if not latest:
            return
        latest_dt = datetime.strptime(latest, '%Y-%m-%d-%H-%M-%S')
        age_hours = (datetime.now() - latest_dt).total_seconds() / 3600
        threshold = cfg.get('max_age_hours', 3)
        if age_hours >= threshold:
            _send_alert_throttled(
                "数据停滞",
                f"最新采样时间 {latest}，距今 {age_hours:.1f} 小时（阈值 {threshold} 小时）",
                "爬虫可能在空转：登录态失效、反爬拦截或调度器未运行。\n"
                "请检查 scheduler.log 与 nga_spider.log。",
                cfg.get('cooldown_minutes', 360)
            )
    except Exception as e:
        logger.debug(f"数据新鲜度检查失败: {e}")


def check_result_alerts(spider_stats: dict, output_lines: list, prev_items=None):
    """基于「本轮实际抓到了什么」发告警，覆盖进程正常但结果异常的情况。"""
    config = scheduler.config if hasattr(scheduler, 'config') else None
    if not config or not email_notifier:
        return
    notifications = config.get('notifications', {})

    # 1) 反爬 / 登录墙
    antibot_alerted = False
    antibot_cfg = notifications.get('antibot_alert', {})
    if antibot_cfg.get('enabled', True):
        hits = sum(1 for line in output_lines if '检测到反爬虫或验证页面' in line)
        threshold = antibot_cfg.get('threshold_per_round', 5)
        if hits >= threshold:
            details = (
                f"命中反爬/登录墙页面的次数: {hits}（阈值 {threshold}）\n"
                f"本轮 item 数: {spider_stats.get('item_scraped_count', 0)}\n\n"
                "常见原因：NGA 登录态失效（页面标题变为「未登录」）或触发访问频率限制。\n"
                "处理：本地运行 get_cookies.py 重新登录，再把 cookies.txt 上传到服务器覆盖。"
            )
            antibot_alerted = _send_alert_throttled(
                "反爬/登录墙", f"本轮检测到 {hits} 次反爬或登录墙页面",
                details, antibot_cfg.get('cooldown_minutes', 360)
            )

    # 2) 抓取量骤降（登录失效不一定每次命中反爬词，但 item 数会塌）
    # 反爬告警已发出时不再重复——两者多半是同一个原因。
    drop_cfg = notifications.get('item_drop_alert', {})
    if drop_cfg.get('enabled', True) and prev_items and not antibot_alerted:
        current = spider_stats.get('item_scraped_count', 0)
        min_prev = drop_cfg.get('min_prev_items', 2000)
        ratio = drop_cfg.get('threshold_ratio', 0.1)
        if prev_items >= min_prev and current < prev_items * ratio:
            details = (
                f"上一轮 item 数: {prev_items}\n"
                f"本轮 item 数: {current}（{current / prev_items * 100:.1f}%）\n\n"
                "常见原因：登录失效、反爬拦截、页面结构变化。请检查 scheduler.log 与 nga_spider.log。"
            )
            _send_alert_throttled(
                "抓取量骤降", f"本轮 item 数仅为上一轮的 {current / prev_items * 100:.0f}%",
                details, drop_cfg.get('cooldown_minutes', 360)
            )


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

        _send_alert_throttled("爬虫连续失败", message, details, 60)

    # 检查超时
    if spider_start_time:
        timeout_minutes = notifications_config.get('spider_timeout_minutes', 60)
        if (datetime.now() - spider_start_time).total_seconds() > timeout_minutes * 60:
            message = f"爬虫运行时间超过 {timeout_minutes} 分钟"
            details = f"开始时间: {spider_start_time}"

            _send_alert_throttled("爬虫运行超时", message, details, 60)

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

            _send_alert_throttled("爬虫错误率过高", message, details, 360)

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

        # 合并数据库与磁盘的真实状态（2026-10-18）：Scrapy 的 item 数不等于入库增长
        stats.update(collect_db_metrics())

        # 提取趋势数据
        trend_data = stats.get('trend_data', {})

        # 发送邮件（包含趋势数据）
        success = email_notifier.send_statistics_report(stats, trend_data=trend_data)

        if success:
            logger.info("统计报告已发送")
            if trend_data.get('has_trend', False):
                logger.info(f"趋势分析: 项目{trend_data.get('items_trend')}, "
                           f"成功率{trend_data.get('success_trend')}, "
                           f"性能{trend_data.get('performance_trend')}")
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

    # 检测是否在screen中运行
    in_screen = os.environ.get('STY') is not None
    if in_screen:
        print("\n" + "=" * 60)
        print("📺 检测到在Screen会话中运行")
        print("   会话名称:", os.environ.get('STY', '未知'))
        print("   提示: 按 Ctrl+\\ 可优雅退出")
        print("=" * 60 + "\n")

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

    # 多平台监测任务（HN / Discourse + NGA→post 同步）：与 NGA spider 错峰 3 分钟
    scheduler.add_job(
        run_monitors_job,
        'interval',
        minutes=30,
        id='monitors_job',
        next_run_time=datetime.now(tz) + timedelta(minutes=3),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300
    )
    logger.info("多平台监测任务已添加：每 30 分钟一轮（与 NGA spider 错峰 3 分钟）")

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

    # 定期清理过期锁
    def cleanup_stale_locks():
        """定期清理过期的锁文件"""
        try:
            lock = ProcessLock(timeout=3600)  # 1小时超时
            if lock._cleanup_stale_lock():
                logger.info("✅ 清理过期锁完成")
        except Exception as e:
            logger.error(f"清理过期锁时出错: {e}")

    # 添加锁清理任务（每10分钟执行一次）
    scheduler.add_job(
        cleanup_stale_locks,
        'interval',
        minutes=10,
        id='cleanup_locks_job',
        max_instances=1
    )
    logger.info("锁清理任务已添加：每10分钟执行一次")

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

                # 获取爬虫状态信息
                spider_status = get_spider_status()
                if spider_process and spider_process.poll() is None:
                    logger.debug(f"调度器运行中 | 爬虫PID: {spider_process.pid} | 下次执行: {next_run}")
                elif spider_status['running']:
                    logger.debug(f"调度器运行中 | 外部爬虫PID: {spider_status.get('pid')} | 运行时长: {spider_status.get('duration', 0):.1f}秒 | 下次执行: {next_run}")
                else:
                    logger.debug(f"调度器运行中 | 下次执行: {next_run}")

            time.sleep(30)

    except KeyboardInterrupt:
        logger.info("收到键盘中断信号")
        signal_handler(signal.SIGINT, None)
