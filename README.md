# NGA_Scrapy

一个基于Scrapy的NGA论坛（bbs.nga.cn）水区爬虫，支持增量爬取、浏览器自动化和定时执行。

## 功能特性

- **增量爬取**: 通过时间戳比较仅获取新内容
- **JavaScript渲染**: 使用Playwright处理动态内容
- **浏览器池**: 复用浏览器实例提高效率
- **图片下载**: 自动下载并存储图片
- **定时执行**: APScheduler可配置间隔执行
- **邮件通知**: 自动发送统计报告和错误告警
- **代理支持**: 内置代理轮换功能（详见 代理使用指南.md）

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
playwright install chromium
```

### 2. 初始化数据库

```bash
python init_db.py
```

### 3. 运行爬虫

```bash
# 基础爬取
scrapy crawl nga

# 使用自定义数据库
scrapy crawl nga -a db_url="sqlite:///custom.db"

# 使用MySQL数据库
scrapy crawl nga -a db_url="mysql://user:pass@localhost/nga_db"
```

### 4. 启动定时调度器（可选）

```bash
cd scheduler
python run_scheduler.py
```

默认每30分钟执行一次。

### 5. 配置邮件通知（可选）

编辑 `scheduler/email_config.yaml`:

```yaml
smtp_server: "smtp.qq.com"
smtp_port: 587
username: "your_email@qq.com"
password: "your_app_password"  # 使用应用密码，不是QQ密码
from_email: "your_email@qq.com"
to_emails:
  - "recipient@example.com"
use_tls: true

notifications:
  enable_statistics_report: true
  statistics_report_interval_days: 3
  enable_error_alerts: true
  consecutive_failures_threshold: 3
```

## 项目结构

```
NGA_Scrapy/
├── NGA_Scrapy/              # 核心Scrapy项目
│   ├── spiders/nga_spider.py    # 主爬虫
│   ├── items.py                 # 数据项定义
│   ├── models.py                # SQLAlchemy模型
│   ├── pipelines.py             # 数据处理管道
│   ├── middlewares.py           # Playwright中间件
│   ├── settings.py              # 爬虫配置
│   └── utils/                   # 工具模块
├── scheduler/                # 调度器和邮件
│   ├── run_scheduler.py         # 调度器守护进程
│   ├── email_notifier.py        # 邮件通知模块
│   └── email_config.yaml        # 邮件配置
├── init_db.py                # 数据库初始化
├── get_cookies.py            # Cookie获取工具
└── requirements.txt          # 依赖列表
```

## 核心组件

### 爬虫 (nga_spider.py)
- 爬取NGA水区 (fid=-7)
- 实现增量爬取策略
- 解析主题、回复和用户信息
- 提取图片URL

### 中间件 (middlewares.py)
- **PlaywrightMiddleware**: 管理浏览器池
- 支持代理轮换
- 处理JavaScript渲染
- 性能监控

### 数据库 (models.py)
- **User**: uid, name, user_group, prestige, reg_date
- **Topic**: tid, title, poster_id, post_time, re_num, last_reply_date
- **Reply**: rid, tid, content, poster_id, post_time, image_urls, image_paths

### 调度器 (scheduler/run_scheduler.py)
- APScheduler后台执行
- 实时日志监控
- 统计数据收集
- 优雅关闭 (SIGINT/SIGTERM)

## 配置说明

### 浏览器设置 (settings.py)
```python
PLAYWRIGHT_POOL_SIZE = 6          # 浏览器池大小
DOWNLOAD_TIMEOUT = 20             # 请求超时时间(秒)
CONCURRENT_REQUESTS = 16          # 并发请求数
IMAGES_STORE = 'download_images'  # 图片存储路径
```

### 邮件设置 (email_config.yaml)
```yaml
# 每3天09:00发送统计报告
statistics_report_interval_days: 3
statistics_report_time: "09:00"

# 错误告警
consecutive_failures_threshold: 3  # 连续失败3次告警
spider_timeout_minutes: 60         # 运行超过60分钟告警
```

## 使用示例

### 基础爬取
```bash
scrapy crawl nga
```

### 自定义数据库
```bash
scrapy crawl nga -a db_url="sqlite:///nga_custom.db"
```

### 调试模式运行
```bash
scrapy crawl nga -L DEBUG
```

### 后台调度器
```bash
# 使用nohup
cd scheduler
nohup python run_scheduler.py > scheduler.log 2>&1 &

# 使用screen
screen -S ngascrape
python run_scheduler.py
# 按 Ctrl+A，然后按 D 脱离会话
```

## 邮件通知

### 统计报告
- **首次报告**: 第一次成功爬取后立即发送
- **定期报告**: 每3天09:00发送（可配置）
- **报告内容**: 爬取统计、成功率、资源使用情况

### 错误告警
- **连续失败**: 连续失败3次以上（可配置）
- **超时告警**: 爬虫运行超过60分钟（可配置）
- **高错误率**: 30分钟窗口内错误率超过10%

### QQ邮箱设置
1. 登录QQ邮箱 → 设置 → 账户
2. 开启"IMAP/SMTP服务"或"POP3/SMTP服务"
3. 发送短信获取应用专用密码
4. 在配置中使用应用密码（非QQ密码）

## 故障排除

### 常见问题

**Q: 浏览器启动失败**
A: 运行 `playwright install chromium` 安装浏览器

**Q: Cookie问题**
A: 运行 `python get_cookies.py` 并在40秒内完成登录

**Q: 调度器无法发送邮件**
A: 检查 `scheduler/scheduler.log` 中的错误；确保QQ邮箱使用应用密码

**Q: 数据库被锁定**
A: 关闭所有数据库连接并重启爬虫

### 日志查看
```bash
# 爬虫日志
tail -f nga_spider.log

# 调度器日志
tail -f scheduler/scheduler.log

# 邮件日志
tail -f scheduler/scheduler.log | grep -i mail
```

### 统计数据
```bash
# 查看最新运行统计
cat scheduler/stats/spider_stats_*.json | jq . | head -50
```

## 数据库架构

### user表
- uid (主键), name, user_group, prestige, reg_date, history_re_num

### topic表
- tid (主键), title, poster_id (外键→user.uid), post_time, re_num, sampling_time, last_reply_date, partition

### reply表
- rid (主键), tid (外键→topic.tid), parent_rid (外键→reply.rid), content, recommendvalue, poster_id (外键→user.uid), post_time, image_urls (JSON), image_paths (JSON), sampling_time

## 开发指南

### 关键修改文件

- **nga_spider.py**: 爬取逻辑、页面解析、时间比较
- **middlewares.py**: 浏览器管理、代理设置
- **settings.py**: 并发、超时、日志配置
- **email_config.yaml**: SMTP和通知设置

### 测试
```bash
# 测试代理配置
python test_proxy_config.py

# 调试XPath解析
python debug_xpath.py
```

## 许可证

MIT许可证

## 贡献指南

1. Fork本项目
2. 创建特性分支
3. 提交Pull Request

## 更新日志

### v1.2.0 (2025-11)
- 新增邮件通知系统
- 新增统计数据收集
- 增强调度器优雅关闭
- 改进日志系统

### v1.1.0
- 优化浏览器池管理
- 改进错误处理

### v1.0.0
- 初始版本发布
- 基础爬取功能
- 增量爬取支持
- 图片下载功能
