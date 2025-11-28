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
        # 格式化邮件内容
        subject = f"NGA爬虫数据统计报告 - {datetime.now().strftime('%Y-%m-%d')}"

        # 纯文本版本
        body_lines = [
            "=" * 60,
            "NGA爬虫数据统计报告",
            "=" * 60,
            f"报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "📊 数据统计:",
            f"  - 新增主题数: {stats.get('new_topics', 0)}",
            f"  - 新增回复数: {stats.get('new_replies', 0)}",
            f"  - 新增用户数: {stats.get('new_users', 0)}",
            f"  - 下载图片数: {stats.get('downloaded_images', 0)}",
            "",
            "⏱️ 运行统计:",
            f"  - 爬取页面数: {stats.get('pages_crawled', 0)}",
            f"  - 请求成功数: {stats.get('requests_success', 0)}",
            f"  - 请求失败数: {stats.get('requests_failed', 0)}",
            f"  - 平均响应时间: {stats.get('avg_response_time', 0):.2f}秒",
            "",
            "⚠️ 错误统计:",
            f"  - HTTP错误: {stats.get('http_errors', 0)}",
            f"  - 解析错误: {stats.get('parse_errors', 0)}",
            f"  - 数据库错误: {stats.get('db_errors', 0)}",
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
                .warning {{ color: #e74c3c; }}
                .success {{ color: #27ae60; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #3498db; color: white; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #7f8c8d; }}
            </style>
        </head>
        <body>
            <h1>📊 NGA爬虫数据统计报告</h1>
            <p><strong>报告时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

            <h2>📈 数据统计</h2>
            <div class="stat-box">
                <div class="stat-item"><span class="label">新增主题数:</span> <span class="value">{stats.get('new_topics', 0)}</span></div>
                <div class="stat-item"><span class="label">新增回复数:</span> <span class="value">{stats.get('new_replies', 0)}</span></div>
                <div class="stat-item"><span class="label">新增用户数:</span> <span class="value">{stats.get('new_users', 0)}</span></div>
                <div class="stat-item"><span class="label">下载图片数:</span> <span class="value">{stats.get('downloaded_images', 0)}</span></div>
            </div>

            <h2>⏱️ 运行统计</h2>
            <div class="stat-box">
                <div class="stat-item"><span class="label">爬取页面数:</span> <span class="value">{stats.get('pages_crawled', 0)}</span></div>
                <div class="stat-item"><span class="label">请求成功数:</span> <span class="value success">{stats.get('requests_success', 0)}</span></div>
                <div class="stat-item"><span class="label">请求失败数:</span> <span class="value warning">{stats.get('requests_failed', 0)}</span></div>
                <div class="stat-item"><span class="label">平均响应时间:</span> <span class="value">{stats.get('avg_response_time', 0):.2f}秒</span></div>
            </div>

            <h2>⚠️ 错误统计</h2>
            <div class="stat-box">
                <div class="stat-item"><span class="label">HTTP错误:</span> <span class="value warning">{stats.get('http_errors', 0)}</span></div>
                <div class="stat-item"><span class="label">解析错误:</span> <span class="value warning">{stats.get('parse_errors', 0)}</span></div>
                <div class="stat-item"><span class="label">数据库错误:</span> <span class="value warning">{stats.get('db_errors', 0)}</span></div>
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

    def __init__(self, log_file: str = "/home/shan/NGA_Scrapy/nga_spider.log"):
        self.log_file = log_file
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
            # 从日志文件解析统计信息
            stats = self._parse_log_statistics(start_date, end_date)

            # 缓存统计数据
            self._cache_statistics(stats)

            return stats
        except Exception as e:
            logger.exception(f"收集统计数据时发生错误: {e}")
            return {}

    def _parse_log_statistics(self, start_date: datetime, end_date: datetime) -> Dict:
        """从日志文件解析统计信息"""
        stats = {
            'new_topics': 0,
            'new_replies': 0,
            'new_users': 0,
            'downloaded_images': 0,
            'pages_crawled': 0,
            'requests_success': 0,
            'requests_failed': 0,
            'http_errors': 0,
            'parse_errors': 0,
            'db_errors': 0,
            'avg_response_time': 0.0,
        }

        # 如果日志文件不存在，返回默认统计
        if not os.path.exists(self.log_file):
            return stats

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            response_times = []

            for line in lines:
                # 解析日志行并统计
                if 'Spider' in line:
                    # 统计爬虫相关信息
                    if 'crawled' in line.lower():
                        stats['pages_crawled'] += line.count('crawled')
                    if 'downloaded' in line.lower():
                        stats['downloaded_images'] += line.count('downloaded')

                # 统计错误
                if 'ERROR' in line:
                    if 'http' in line.lower():
                        stats['http_errors'] += 1
                    if 'parse' in line.lower():
                        stats['parse_errors'] += 1
                    if 'database' in line.lower() or 'db' in line.lower():
                        stats['db_errors'] += 1

            # 计算平均响应时间
            if response_times:
                stats['avg_response_time'] = sum(response_times) / len(response_times)

            # 从日志中提取更多统计信息（简化版）
            stats['requests_success'] = stats['pages_crawled']  # 假设每个页面都是一个请求
            stats['requests_failed'] = stats['http_errors']

        except Exception as e:
            logger.exception(f"解析日志文件时发生错误: {e}")

        return stats

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
