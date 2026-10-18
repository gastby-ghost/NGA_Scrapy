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


def _sparkline(values: list) -> str:
    """Unicode 块字符迷你趋势图（2026-10-18）。

    纯文本与 HTML 邮件都能显示，不依赖外部图片。0 值会显示为最低块，
    缺失日期已在采集端补 0，因此能直观看出"哪几天断了"。
    """
    if not values:
        return ''
    lo, hi = min(values), max(values)
    if hi == lo:
        return '█' * len(values)
    chars = '▁▂▃▄▅▆▇█'
    return ''.join(chars[int((v - lo) / (hi - lo) * (len(chars) - 1))] for v in values)


class AsciiChartGenerator:
    """ASCII图表生成器，用于在纯文本邮件中显示简单的趋势图表"""

    @staticmethod
    def generate_line_chart(data_points: list, width: int = 50, height: int = 10) -> str:
        """
        生成简单的ASCII线形图

        Args:
            data_points: 数据点列表
            width: 图表宽度（字符数）
            height: 图表高度（字符数）

        Returns:
            str: ASCII图表字符串
        """
        if not data_points or len(data_points) < 2:
            return "数据不足，无法生成图表"

        # 归一化数据
        min_val = min(data_points)
        max_val = max(data_points)
        if min_val == max_val:
            return "数据无变化"

        # 计算每个数据点对应的坐标
        chart_lines = []
        for y in range(height - 1, -1, -1):
            line = ""
            for x in range(width):
                idx = int(x * (len(data_points) - 1) / (width - 1))
                val = data_points[idx]

                # 归一化值到 0-height 范围
                normalized = (val - min_val) / (max_val - min_val) * (height - 1)

                # 判断是否应该绘制点
                if abs(normalized - y) < 0.5:
                    line += "●"
                else:
                    line += " "
            chart_lines.append(line)

        # 添加Y轴标签
        max_line = f"{max_val:.1f}".ljust(8)
        min_line = f"{min_val:.1f}".ljust(8)
        chart_lines[0] = max_line + chart_lines[0]
        chart_lines[-1] = min_line + chart_lines[-1]

        return "\n".join(chart_lines)


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
                        logger.debug(f"已添加附件: {file_path}")

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

    def send_statistics_report(self, stats: Dict, report_file: Optional[str] = None,
                                trend_data: Optional[Dict] = None) -> bool:
        """
        发送数据统计报告

        Args:
            stats: 统计数据字典
            report_file: 报告文件路径
            trend_data: 趋势数据（包含最近几天的统计）

        Returns:
            bool: 发送是否成功
        """
        # ---- 数据准备（2026-10-18 精简版：一屏看完，含时长分布） ----
        daily = stats.get('db_daily_replies') or {}
        age = stats.get('db_latest_age_hours')

        # 最近轮次时长分布
        runtimes = stats.get('recent_runtimes') or []
        rt_values = [r[1] for r in runtimes if r[1]]
        rt_last = rt_values[-1] if rt_values else 0
        rt_median = sorted(rt_values)[len(rt_values) // 2] if rt_values else 0
        rt_max = max(rt_values) if rt_values else 0

        if age is None:
            state_line = "状态未知"
        elif age >= 3:
            state_line = f"❌ 数据停滞（最新数据 {age:.1f} 小时前）"
        elif age >= 1.5:
            state_line = f"⚠️ 数据延迟（最新数据 {age:.1f} 小时前）"
        else:
            state_line = f"✅ 采集正常（最新数据 {age:.1f} 小时前）"

        # 主题：状态直接可见
        subject = f"NGA爬虫数据统计报告 - {datetime.now().strftime('%Y-%m-%d')}"
        if age is not None and age >= 3:
            subject = "❌ 数据停滞 - " + subject
        elif age is not None and age >= 1.5:
            subject = "⚠️ 数据延迟 - " + subject

        # 纯文本版本（一屏）
        body_lines = [
            "=" * 60,
            "NGA 爬虫统计报告",
            "=" * 60,
            f"报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"状态: {state_line}",
            "",
        ]
        if 'db_reply_total' in stats:
            body_lines += [
                "📦 数据",
                f"  累计: 回复 {stats.get('db_reply_total', 0):,} · 主题 {stats.get('db_topic_total', 0):,} · 用户 {stats.get('db_user_total', 0):,}",
            ]
            if daily:
                days = sorted(daily)
                vals = [daily[d] for d in days]
                body_lines.append(
                    f"  近 7 天: {_sparkline(vals)}  "
                    + " ".join(f"{d[5:]}:{n:,}" for d, n in zip(days, vals)))
            body_lines += [
                f"  最新采样: {stats.get('db_latest_sampling', 'N/A')}",
                f"  库 {stats.get('db_size_pretty', 'N/A')} · 图片 {stats.get('images_files', 0):,} 个 / {stats.get('images_size_mb', 0):.1f} MB",
                "",
            ]
        body_lines += [
            "⏱️ 爬虫",
            f"  最近 {len(rt_values)} 轮时长(秒): {_sparkline(rt_values)}",
            f"  本轮 {rt_last:.0f}s · 中位 {rt_median:.0f}s · 最长 {rt_max:.0f}s",
            f"  成功率 {stats.get('success_rate', 0):.0f}% · 抓取条目 {stats.get('items_scraped', 0):,} · 反爬命中 {stats.get('antibot_hits', 0)}",
            "=" * 60,
        ]
        body = "\n".join(body_lines)

        # HTML版本
        # 数据入库 HTML（2026-10-18 新增；旧版报告无这些字段时整段跳过）
        db_html = ""
        if 'db_reply_total' in stats:
            daily = stats.get('db_daily_replies') or {}
            age = stats.get('db_latest_age_hours')

            # 状态徽章：绿 / 黄 / 红对应采集正常 / 延迟 / 停滞
            if age is None:
                status_html = ""
            elif age >= 3:
                status_html = (
                    '<div style="background:#ffebee;border-left:4px solid #c62828;'
                    'padding:12px 16px;margin-bottom:20px;border-radius:4px;color:#b71c1c;">'
                    f'<strong>❌ 数据停滞</strong> · 最新数据 {age:.1f} 小时前</div>'
                )
            elif age >= 1.5:
                status_html = (
                    '<div style="background:#fff8e1;border-left:4px solid #f9a825;'
                    'padding:12px 16px;margin-bottom:20px;border-radius:4px;color:#8d6e00;">'
                    f'<strong>⚠️ 数据延迟</strong> · 最新数据 {age:.1f} 小时前</div>'
                )
            else:
                status_html = (
                    '<div style="background:#e8f5e9;border-left:4px solid #2e7d32;'
                    'padding:12px 16px;margin-bottom:20px;border-radius:4px;color:#1b5e20;">'
                    f'<strong>✅ 采集正常</strong> · 最新数据 {age:.1f} 小时前</div>'
                )

            # 近 7 天每日入库条形图（table 布局，兼容邮件客户端）
            days = sorted(daily)
            vals = [daily[d] for d in days]
            max_daily = max(vals) if vals else 0
            bars = ""
            for d, n in zip(days, vals):
                pct = (n / max_daily * 100) if max_daily else 0
                bars += (
                    '<tr>'
                    f'<td style="width:92px;font-size:13px;color:#555;padding:3px 0;">{d}</td>'
                    '<td style="padding:3px 10px;">'
                    '<div style="background:#eef1f5;height:16px;border-radius:3px;">'
                    f'<div style="width:{pct:.1f}%;height:16px;background:#667eea;border-radius:3px;"></div>'
                    '</div></td>'
                    f'<td style="width:70px;text-align:right;font-size:13px;color:#333;">{n:,}</td>'
                    '</tr>'
                )
            spark = _sparkline(vals)

            db_html = f"""
                    {status_html}
                    <h2>📦 数据入库</h2>
                    <div class="stats-grid">
                        <div class="stat-card"><div class="label">累计主题</div><div class="number">{stats.get('db_topic_total', 0):,}</div></div>
                        <div class="stat-card"><div class="label">累计回复</div><div class="number">{stats.get('db_reply_total', 0):,}</div></div>
                        <div class="stat-card"><div class="label">累计用户</div><div class="number">{stats.get('db_user_total', 0):,}</div></div>
                        <div class="stat-card"><div class="label">数据库大小</div><div class="number">{stats.get('db_size_pretty', 'N/A')}</div></div>
                    </div>
                    <div class="stat-box">
                        <div style="font-size:13px;color:#555;margin-bottom:6px;">近 7 天每日入库（条）</div>
                        <div style="font-family:monospace;font-size:20px;letter-spacing:3px;color:#667eea;margin-bottom:10px;">{spark}</div>
                        <table style="width:100%;border-collapse:collapse;">{bars}</table>
                    </div>
                    <div class="stat-box">
                        <div class="stat-item"><span class="label">最新采样时间</span><span class="value">{stats.get('db_latest_sampling', 'N/A')}</span></div>
                        <div class="stat-item"><span class="label">图片文件</span><span class="value">{stats.get('images_files', 0):,} 个 / {stats.get('images_size_mb', 0):.1f} MB</span></div>
                    </div>
                    <div class="divider"></div>
            """

        html_body = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background-color: #f5f7fa;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 800px;
                    margin: 0 auto;
                    background-color: white;
                    border-radius: 12px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                    overflow: hidden;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 28px;
                    font-weight: 600;
                }}
                .header p {{
                    margin: 10px 0 0 0;
                    opacity: 0.9;
                    font-size: 14px;
                }}
                .content {{
                    padding: 30px;
                }}
                h2 {{
                    color: #2c3e50;
                    margin-top: 30px;
                    margin-bottom: 15px;
                    font-size: 20px;
                    font-weight: 600;
                    border-left: 4px solid #667eea;
                    padding-left: 12px;
                }}
                h2:first-child {{
                    margin-top: 0;
                }}
                .stat-box {{
                    background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
                    padding: 20px;
                    margin: 15px 0;
                    border-radius: 8px;
                    border: 1px solid #e1e8ed;
                }}
                .stat-item {{
                    margin: 12px 0;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }}
                .label {{
                    font-weight: 500;
                    color: #555;
                    font-size: 14px;
                }}
                .value {{
                    color: #667eea;
                    font-weight: 600;
                    font-size: 16px;
                }}
                .success {{ color: #27ae60; }}
                .warning {{ color: #e74c3c; }}
                .info {{ color: #3498db; }}
                .trend {{
                    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                }}
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    margin: 15px 0;
                }}
                .stat-card {{
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    border: 1px solid #e1e8ed;
                    text-align: center;
                }}
                .stat-card .number {{
                    font-size: 24px;
                    font-weight: 700;
                    color: #667eea;
                    margin: 5px 0;
                }}
                .stat-card .label {{
                    font-size: 12px;
                    color: #7f8c8d;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }}
                .footer {{
                    margin-top: 40px;
                    padding: 20px;
                    background-color: #f8f9fa;
                    text-align: center;
                    font-size: 12px;
                    color: #7f8c8d;
                    border-top: 1px solid #e1e8ed;
                }}
                .divider {{
                    height: 1px;
                    background: linear-gradient(to right, transparent, #e1e8ed, transparent);
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📊 NGA爬虫数据统计报告</h1>
                    <p>报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>

                <div class="content">
                    {db_html}

                    <h2>⏱️ 爬虫运行</h2>
                    <div class="stat-box">
                        <div style="font-size:13px;color:#555;margin-bottom:6px;">最近 {len(rt_values)} 轮时长（秒）</div>
                        <div style="font-family:monospace;font-size:20px;letter-spacing:3px;color:#667eea;margin-bottom:10px;">{_sparkline(rt_values)}</div>
                        <div class="stat-item"><span class="label">本轮</span><span class="value">{rt_last:.0f}s</span></div>
                        <div class="stat-item"><span class="label">中位</span><span class="value">{rt_median:.0f}s</span></div>
                        <div class="stat-item"><span class="label">最长</span><span class="value">{rt_max:.0f}s</span></div>
                    </div>

                    <h2>📊 技术指标</h2>
                    <div class="stat-box">
                        <div class="stat-item"><span class="label">成功率</span><span class="value success">{stats.get('success_rate', 0):.0f}%</span></div>
                        <div class="stat-item"><span class="label">抓取条目（含重复）</span><span class="value">{stats.get('items_scraped', 0):,}</span></div>
                        <div class="stat-item"><span class="label">抓取页面</span><span class="value">{stats.get('pages_crawled', 0):,}</span></div>
                        <div class="stat-item"><span class="label">反爬/登录墙命中</span><span class="value warning">{stats.get('antibot_hits', 0)} 次</span></div>
                    </div>

                    <div class="divider"></div>
                </div>

                <div class="footer">
                    <p>此报告由NGA爬虫调度器自动生成</p>
                    <p>Report generated by NGA Spider Scheduler</p>
                </div>
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
            'avg_crawl_speed': 0.0,
            'avg_page_size': 0.0,
            'antibot_hits': 0,
        }

        # 用于趋势分析的历史数据
        daily_stats = {}  # 按天聚合的数据
        recent_runs = []  # 最近轮次 (时间标签, 运行秒数)，用于邮件中的时长分布

        # 如果统计目录不存在，返回默认统计
        if not os.path.exists(self.stats_dir):
            logger.warning(f"统计目录不存在: {self.stats_dir}")
            return aggregated_stats

        try:
            import glob
            from datetime import datetime as dt

            # 获取所有统计文件（文件名含时间戳，排序即时间序；2026-10-18 修复：
            # 原实现依赖 glob 返回顺序，latest_status 可能取到任意一次的状态）
            stats_files = sorted(glob.glob(os.path.join(self.stats_dir, "spider_stats_*.json")))

            if not stats_files:
                logger.warning(f"未找到统计文件: {self.stats_dir}")
                return aggregated_stats

            logger.debug(f"找到 {len(stats_files)} 个统计文件")

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
                        items_scraped = spider_stats.get('item_scraped_count', 0)
                        pages_crawled = spider_stats.get('downloader/response_count', 0)
                        dupefilter_filtered = spider_stats.get('dupefilter/filtered', 0)
                        response_bytes = spider_stats.get('downloader/response_bytes', 0)

                        aggregated_stats['items_scraped'] += items_scraped
                        aggregated_stats['pages_crawled'] += pages_crawled
                        aggregated_stats['dupefilter_filtered'] += dupefilter_filtered
                        aggregated_stats['response_bytes'] += response_bytes
                        aggregated_stats['antibot_hits'] += spider_stats.get('custom/antibot_hits', 0)

                        # 统计成功/失败
                        if data.get('success', False):
                            aggregated_stats['successful_runs'] += 1
                        else:
                            aggregated_stats['failed_runs'] += 1

                        # 累加运行时间
                        runtime = spider_stats.get('elapsed_time_seconds', 0) or summary.get('runtime_seconds', 0)
                        aggregated_stats['total_runtime'] += runtime
                        recent_runs.append((file_timestamp.strftime('%m-%d %H:%M'), runtime))

                        # 按天聚合数据用于趋势分析
                        day_key = file_timestamp.strftime('%Y-%m-%d')
                        if day_key not in daily_stats:
                            daily_stats[day_key] = {
                                'items_scraped': 0,
                                'pages_crawled': 0,
                                'successful_runs': 0,
                                'total_runs': 0,
                                'total_runtime': 0.0,
                            }

                        daily_stats[day_key]['items_scraped'] += items_scraped
                        daily_stats[day_key]['pages_crawled'] += pages_crawled
                        daily_stats[day_key]['total_runs'] += 1
                        daily_stats[day_key]['total_runtime'] += runtime
                        if data.get('success', False):
                            daily_stats[day_key]['successful_runs'] += 1

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
                avg_bytes = aggregated_stats['response_bytes'] / aggregated_stats['total_runs']
                aggregated_stats['avg_download_speed'] = avg_bytes / (1024 * 1024)
                # 平均爬取速度 (页/分钟)
                if aggregated_stats['total_runtime'] > 0:
                    aggregated_stats['avg_crawl_speed'] = (aggregated_stats['pages_crawled'] / aggregated_stats['total_runs']) / (aggregated_stats['avg_runtime'] / 60)
                # 单页平均大小 (KB)
                if aggregated_stats['pages_crawled'] > 0:
                    aggregated_stats['avg_page_size'] = (aggregated_stats['response_bytes'] / aggregated_stats['pages_crawled']) / 1024
            else:
                aggregated_stats['avg_runtime'] = 0.0
                aggregated_stats['success_rate'] = 0.0
                aggregated_stats['avg_download_speed'] = 0.0
                aggregated_stats['avg_crawl_speed'] = 0.0
                aggregated_stats['avg_page_size'] = 0.0

            # 添加最新状态
            aggregated_stats['latest_status'] = latest_status

            # 最近 12 轮运行时长（邮件中的时长分布，2026-10-18）
            recent_runs.sort(key=lambda x: x[0])
            aggregated_stats['recent_runtimes'] = recent_runs[-12:]

            # 趋势分析
            if len(daily_stats) >= 2:
                sorted_days = sorted(daily_stats.keys())
                first_day = sorted_days[0]
                last_day = sorted_days[-1]

                first_day_stats = daily_stats[first_day]
                last_day_stats = daily_stats[last_day]

                # 计算趋势
                items_trend = self._calculate_trend(
                    first_day_stats['items_scraped'],
                    last_day_stats['items_scraped']
                )

                success_trend = self._calculate_trend(
                    (first_day_stats['successful_runs'] / first_day_stats['total_runs'] * 100) if first_day_stats['total_runs'] > 0 else 0,
                    (last_day_stats['successful_runs'] / last_day_stats['total_runs'] * 100) if last_day_stats['total_runs'] > 0 else 0
                )

                performance_trend = self._calculate_trend(
                    (first_day_stats['pages_crawled'] / first_day_stats['total_runtime'] * 60) if first_day_stats['total_runtime'] > 0 else 0,
                    (last_day_stats['pages_crawled'] / last_day_stats['total_runtime'] * 60) if last_day_stats['total_runtime'] > 0 else 0
                )

                aggregated_stats['trend_data'] = {
                    'has_trend': True,
                    'items_trend': items_trend,
                    'success_trend': success_trend,
                    'performance_trend': performance_trend,
                    'analysis_period': f"{first_day} 至 {last_day}",
                    'days_analyzed': len(daily_stats)
                }
            else:
                aggregated_stats['trend_data'] = {
                    'has_trend': False
                }

            logger.debug(f"成功聚合了 {file_count} 个统计文件的数据")
            logger.debug(f"统计汇总: 总执行次数={aggregated_stats['total_runs']}, "
                       f"成功={aggregated_stats['successful_runs']}, "
                       f"失败={aggregated_stats['failed_runs']}")
            logger.debug(f"累计抓取项目: {aggregated_stats['items_scraped']}, "
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

    def _calculate_trend(self, old_value: float, new_value: float) -> str:
        """
        计算趋势并返回描述字符串

        Args:
            old_value: 旧值
            new_value: 新值

        Returns:
            str: 趋势描述（如 "↗️ 上升 15.2%" 或 "↘️ 下降 5.3%" 或 "→ 持平"）
        """
        if old_value == 0:
            if new_value == 0:
                return "→ 持平"
            else:
                return f"↗️ 新增 {new_value:.2f}"

        change_percent = ((new_value - old_value) / old_value) * 100

        if abs(change_percent) < 1:  # 变化小于1%视为持平
            return "→ 持平"
        elif change_percent > 0:
            return f"↗️ 上升 {change_percent:.1f}%"
        else:
            return f"↘️ 下降 {abs(change_percent):.1f}%"
