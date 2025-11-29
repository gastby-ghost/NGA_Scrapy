"""
邮件通知模块
负责发送爬虫数据统计报告和告警邮件
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import os
import json

logger = logging.getLogger(__name__)

# 获取项目根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)


class EmailNotifier:
    """SMTP邮件发送器"""

    def __init__(self, smtp_server: str, smtp_port: int, username: str, password: str,
                 from_email: str, to_emails: List[str], use_tls: bool = True):
        """
        初始化邮件发送器

        Args:
            smtp_server: SMTP服务器地址
            smtp_port: SMTP端口
            username: SMTP用户名
            password: SMTP密码或应用专用密码
            from_email: 发件人邮箱
            to_emails: 收件人邮箱列表
            use_tls: 是否使用TLS加密
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.to_emails = to_emails
        self.use_tls = use_tls

    def send_email(self, subject: str, body: str, html_body: Optional[str] = None,
                   attachments: Optional[List[str]] = None) -> bool:
        """
        发送邮件

        Args:
            subject: 邮件主题
            body: 邮件正文（纯文本）
            html_body: 邮件正文（HTML格式）
            attachments: 附件文件路径列表

        Returns:
            bool: 发送是否成功
        """
        try:
            # 创建邮件对象
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = ', '.join(self.to_emails)

            # 添加纯文本正文
            text_part = MIMEText(body, 'plain', 'utf-8')
            msg.attach(text_part)

            # 添加HTML正文
            if html_body:
                html_part = MIMEText(html_body, 'html', 'utf-8')
                msg.attach(html_part)

            # 添加附件
            if attachments:
                for file_path in attachments:
                    if os.path.exists(file_path):
                        with open(file_path, 'rb') as f:
                            part = MIMEBase('application', 'octet-stream')
                            part.set_payload(f.read())

                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename= {os.path.basename(file_path)}'
                        )
                        msg.attach(part)
                        logger.info(f"已添加附件: {file_path}")

            # 发送邮件
            try:
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    if self.use_tls:
                        server.starttls()
                    server.login(self.username, self.password)
                    text = msg.as_string()
                    server.sendmail(self.from_email, self.to_emails, text)

                logger.info(f"邮件发送成功: {subject}")
                return True

            except smtplib.SMTPResponseException as e:
                # 处理已知的smtplib bug: (-1, b'\x00\x00\x00')
                # 这个异常在实际邮件发送成功后仍可能出现
                if e.smtp_code == -1 and e.smtp_error == b'\x00\x00\x00':
                    logger.info(f"邮件发送成功: {subject} (SMTPResponseException已被忽略)")
                    return True
                else:
                    logger.exception(f"邮件发送失败: {e}")
                    return False

        except Exception as e:
            logger.exception(f"邮件发送失败: {e}")
            return False

    def send_statistics_report(self, stats: Dict, report_file: Optional[str] = None) -> bool:
        """
        发送数据统计报告

        Args:
            stats: 统计数据字典
            report_file: 报告文件路径

        Returns:
            bool: 发送是否成功
        """
        # 计算下载数据大小（MB）
        downloaded_mb = stats.get('response_bytes', 0) / (1024 * 1024)

        # 格式化邮件内容
        subject = f"NGA爬虫数据统计报告 - {datetime.now().strftime('%Y-%m-%d')}"

        # 纯文本版本
        body_lines = [
            "=" * 60,
            "NGA爬虫数据统计报告",
            "=" * 60,
            f"报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "📊 爬取统计:",
            f"  - 抓取项目总数: {stats.get('items_scraped', 0)}",
            f"  - 爬取页面总数: {stats.get('pages_crawled', 0)}",
            f"  - 去重过滤数: {stats.get('dupefilter_filtered', 0)}",
            "",
            "📈 运行统计:",
            f"  - 总执行次数: {stats.get('total_runs', 0)}",
            f"  - 成功执行次数: {stats.get('successful_runs', 0)}",
            f"  - 失败执行次数: {stats.get('failed_runs', 0)}",
            f"  - 总运行时间: {stats.get('total_runtime', 0):.2f}秒",
            f"  - 平均执行时间: {stats.get('avg_runtime', 0):.2f}秒/次",
            "",
            "💾 资源消耗:",
            f"  - 下载数据总量: {downloaded_mb:.2f} MB",
            f"  - 平均下载速度: {stats.get('avg_download_speed', 0):.2f} MB/次",
            "",
            "✅ 执行状态:",
            f"  - 执行成功率: {stats.get('success_rate', 0):.1f}%",
            f"  - 最近执行状态: {stats.get('latest_status', 'unknown')}",
            "",
            "=" * 60,
        ]
        body = "\n".join(body_lines)

        # HTML版本
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
                h2 {{ color: #34495e; margin-top: 20px; }}
                .stat-box {{ background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; }}
                .stat-item {{ margin: 5px 0; }}
                .label {{ font-weight: bold; color: #555; }}
                .value {{ color: #2980b9; }}
                .success {{ color: #27ae60; }}
                .warning {{ color: #e74c3c; }}
                .info {{ color: #3498db; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #7f8c8d; }}
            </style>
        </head>
        <body>
            <h1>📊 NGA爬虫数据统计报告</h1>
            <p><strong>报告时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

            <h2>📈 爬取统计</h2>
            <div class="stat-box">
                <div class="stat-item"><span class="label">抓取项目总数:</span> <span class="value">{stats.get('items_scraped', 0)}</span></div>
                <div class="stat-item"><span class="label">爬取页面总数:</span> <span class="value">{stats.get('pages_crawled', 0)}</span></div>
                <div class="stat-item"><span class="label">去重过滤数:</span> <span class="value">{stats.get('dupefilter_filtered', 0)}</span></div>
            </div>

            <h2>⏱️ 运行统计</h2>
            <div class="stat-box">
                <div class="stat-item"><span class="label">总执行次数:</span> <span class="value">{stats.get('total_runs', 0)}</span></div>
                <div class="stat-item"><span class="label">成功执行次数:</span> <span class="value success">{stats.get('successful_runs', 0)}</span></div>
                <div class="stat-item"><span class="label">失败执行次数:</span> <span class="value warning">{stats.get('failed_runs', 0)}</span></div>
                <div class="stat-item"><span class="label">总运行时间:</span> <span class="value">{stats.get('total_runtime', 0):.2f}秒</span></div>
                <div class="stat-item"><span class="label">平均执行时间:</span> <span class="value">{stats.get('avg_runtime', 0):.2f}秒/次</span></div>
            </div>

            <h2>💾 资源消耗</h2>
            <div class="stat-box">
                <div class="stat-item"><span class="label">下载数据总量:</span> <span class="value">{downloaded_mb:.2f} MB</span></div>
                <div class="stat-item"><span class="label">平均下载速度:</span> <span class="value">{stats.get('avg_download_speed', 0):.2f} MB/次</span></div>
            </div>

            <h2>✅ 执行状态</h2>
            <div class="stat-box">
                <div class="stat-item"><span class="label">执行成功率:</span> <span class="value success">{stats.get('success_rate', 0):.1f}%</span></div>
                <div class="stat-item"><span class="label">最近执行状态:</span> <span class="value info">{stats.get('latest_status', 'unknown')}</span></div>
            </div>

            <div class="footer">
                <p>此邮件由NGA爬虫调度器自动发送</p>
            </div>
        </body>
        </html>
        """

        # 发送邮件
        attachments = [report_file] if report_file and os.path.exists(report_file) else None
        return self.send_email(subject, body, html_body, attachments)

    def send_alert(self, alert_type: str, message: str, details: Optional[str] = None) -> bool:
        """
        发送告警邮件

        Args:
            alert_type: 告警类型（错误率过高/无法访问/其他）
            message: 告警消息
            details: 详细错误信息

        Returns:
            bool: 发送是否成功
        """
        subject = f"⚠️ NGA爬虫告警: {alert_type} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        body_lines = [
            "=" * 60,
            "NGA爬虫系统告警",
            "=" * 60,
            f"告警时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"告警类型: {alert_type}",
            "",
            "告警内容:",
            message,
            "",
        ]

        if details:
            body_lines.extend([
                "详细信息:",
                details,
                "",
            ])

        body_lines.extend([
            "=" * 60,
            "请及时处理此告警！",
        ])

        body = "\n".join(body_lines)

        # HTML版本
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                h1 {{ color: #e74c3c; border-bottom: 2px solid #e74c3c; padding-bottom: 10px; }}
                .alert-box {{ background: #ffe6e6; padding: 20px; margin: 20px 0; border-left: 5px solid #e74c3c; border-radius: 5px; }}
                .details-box {{ background: #f8f9fa; padding: 15px; margin: 15px 0; border-radius: 5px; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #7f8c8d; }}
            </style>
        </head>
        <body>
            <h1>⚠️ NGA爬虫系统告警</h1>

            <div class="alert-box">
                <p><strong>告警时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><strong>告警类型:</strong> {alert_type}</p>
                <p><strong>告警内容:</strong></p>
                <p>{message}</p>
            </div>

            {f'''
            <div class="details-box">
                <p><strong>详细信息:</strong></p>
                <pre>{details}</pre>
            </div>
            ''' if details else ''}

            <div class="footer">
                <p>请及时处理此告警！</p>
                <p>此邮件由NGA爬虫调度器自动发送</p>
            </div>
        </body>
        </html>
        """

        return self.send_email(subject, body, html_body)


class StatisticsCollector:
    """统计数据收集器"""

    def __init__(self, stats_dir: str = None):
        self.stats_dir = stats_dir or os.path.join(SCRIPT_DIR, "stats")
        self.stats_cache_file = "/tmp/nga_spider_stats.json"

    def collect_statistics(self, start_date: datetime, end_date: datetime) -> Dict:
        """
        收集指定时间段的统计数据

        Args:
            start_date: 开始时间
            end_date: 结束时间

        Returns:
            Dict: 统计数据
        """
        try:
            # 从 JSON 统计文件解析统计信息
            stats = self._parse_json_statistics(start_date, end_date)

            # 缓存统计数据
            self._cache_statistics(stats)

            return stats
        except Exception as e:
            logger.exception(f"收集统计数据时发生错误: {e}")
            return {}

    def _parse_json_statistics(self, start_date: datetime, end_date: datetime) -> Dict:
        """从 JSON 统计文件解析统计信息"""
        aggregated_stats = {
            'items_scraped': 0,
            'pages_crawled': 0,
            'dupefilter_filtered': 0,
            'response_bytes': 0,
            'total_runtime': 0.0,
            'total_runs': 0,
            'successful_runs': 0,
            'failed_runs': 0,
        }

        # 如果统计目录不存在，返回默认统计
        if not os.path.exists(self.stats_dir):
            logger.warning(f"统计目录不存在: {self.stats_dir}")
            return aggregated_stats

        try:
            import glob
            from datetime import datetime as dt

            # 获取所有统计文件
            stats_files = glob.glob(os.path.join(self.stats_dir, "spider_stats_*.json"))

            if not stats_files:
                logger.warning(f"未找到统计文件: {self.stats_dir}")
                return aggregated_stats

            logger.info(f"找到 {len(stats_files)} 个统计文件")

            file_count = 0
            latest_status = 'unknown'

            for stats_file in stats_files:
                try:
                    with open(stats_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    # 解析文件时间戳
                    file_timestamp = dt.fromisoformat(data['timestamp'])

                    # 检查时间范围
                    if start_date <= file_timestamp <= end_date:
                        file_count += 1
                        aggregated_stats['total_runs'] += 1

                        # 更新最新状态
                        latest_status = '成功' if data.get('success', False) else '失败'

                        # 聚合统计数据
                        spider_stats = data.get('spider_stats', {})
                        summary = data.get('summary', {})

                        # 累加关键指标
                        aggregated_stats['items_scraped'] += spider_stats.get('item_scraped_count', 0)
                        aggregated_stats['pages_crawled'] += spider_stats.get('downloader/response_count', 0)
                        aggregated_stats['dupefilter_filtered'] += spider_stats.get('dupefilter/filtered', 0)
                        aggregated_stats['response_bytes'] += spider_stats.get('downloader/response_bytes', 0)

                        # 统计成功/失败
                        if data.get('success', False):
                            aggregated_stats['successful_runs'] += 1
                        else:
                            aggregated_stats['failed_runs'] += 1

                        # 累加运行时间
                        runtime = spider_stats.get('elapsed_time_seconds', 0) or summary.get('runtime_seconds', 0)
                        aggregated_stats['total_runtime'] += runtime

                except Exception as e:
                    logger.warning(f"解析统计文件 {stats_file} 时发生错误: {e}")
                    continue

            # 计算衍生指标
            if aggregated_stats['total_runs'] > 0:
                # 平均运行时间
                aggregated_stats['avg_runtime'] = aggregated_stats['total_runtime'] / aggregated_stats['total_runs']
                # 成功率
                aggregated_stats['success_rate'] = (aggregated_stats['successful_runs'] / aggregated_stats['total_runs']) * 100
                # 平均下载速度 (MB/次)
                if aggregated_stats['total_runs'] > 0:
                    avg_bytes = aggregated_stats['response_bytes'] / aggregated_stats['total_runs']
                    aggregated_stats['avg_download_speed'] = avg_bytes / (1024 * 1024)
            else:
                aggregated_stats['avg_runtime'] = 0.0
                aggregated_stats['success_rate'] = 0.0
                aggregated_stats['avg_download_speed'] = 0.0

            # 添加最新状态
            aggregated_stats['latest_status'] = latest_status

            logger.info(f"成功聚合了 {file_count} 个统计文件的数据")
            logger.info(f"统计汇总: 总执行次数={aggregated_stats['total_runs']}, "
                       f"成功={aggregated_stats['successful_runs']}, "
                       f"失败={aggregated_stats['failed_runs']}")
            logger.info(f"累计抓取项目: {aggregated_stats['items_scraped']}, "
                       f"累计爬取页面: {aggregated_stats['pages_crawled']}")

        except Exception as e:
            logger.exception(f"解析 JSON 统计文件时发生错误: {e}")

        return aggregated_stats

    def _cache_statistics(self, stats: Dict):
        """缓存统计数据"""
        try:
            with open(self.stats_cache_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception(f"缓存统计数据时发生错误: {e}")

    def get_cached_statistics(self) -> Dict:
        """获取缓存的统计数据"""
        try:
            if os.path.exists(self.stats_cache_file):
                with open(self.stats_cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.exception(f"读取缓存统计数据时发生错误: {e}")

        return {}
