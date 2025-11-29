# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NGA_Scrapy is a Scrapy-based web scraper for NGA forum (bbs.nga.cn) that crawls the water zone (fid=-7). It implements incremental crawling to only fetch new content, avoiding duplicates. The project uses Playwright for JavaScript rendering, SQLAlchemy for ORM, and supports scheduled crawling.

## Common Commands

### Setup Virtual Environment (Prerequisite)

```bash
# Check if virtual environment exists
ls -la venv/

# Create virtual environment (if not exists)
python3 -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Verify activation (should show venv path)
which python  # Linux/Mac
where python   # Windows
```

### Installation & Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Initialize database
python init_db.py

# Get cookies for authenticated crawling (optional)
python get_cookies.py
```

### Running the Spider

```bash
# Basic crawling
scrapy crawl nga

# Crawl with custom database
scrapy crawl nga -a db_url="sqlite:///custom_nga.db"

# Crawl with MySQL
scrapy crawl nga -a db_url="mysql://user:password@localhost/nga_db"

# Crawl with PostgreSQL
scrapy crawl nga -a db_url="postgresql://user:password@localhost/nga_db"
```

### Scheduled Crawling

```bash
cd scheduler
python run_scheduler.py
```

Default runs every 30 minutes. Configure email notifications by editing `scheduler/email_config.yaml`.

### Email Configuration (Optional)

Configure email notifications for statistics reports and error alerts:

```bash
# Copy and edit the email config
cd scheduler
# Edit email_config.yaml with your SMTP settings
# For QQ Mail: Use app-specific password from mail settings
```

Configure:
- SMTP server settings (host, port, credentials)
- Recipient email addresses
- Statistics report interval (default: every 3 days at 09:00)
- Error alert thresholds (consecutive failures, timeout, error rate)

## High-Level Architecture

### Core Components

1. **Spider** (`NGA_Scrapy/spiders/nga_spider.py:1-405`)
   - `NgaSpider` class: Main crawling logic
   - Implements incremental crawling by comparing timestamps
   - Parses topic lists, replies, and user info
   - Uses time-based filtering to avoid duplicate content

2. **Database Models** (`NGA_Scrapy/models.py:1-50`)
   - Three main tables: `User`, `Topic`, `Reply`
   - `Reply` has JSON fields for image URLs and local paths
   - Uses SQLAlchemy declarative base

3. **Items** (`NGA_Scrapy/items.py:1-33`)
   - `UserItem`: User information (uid, user_group, reg_date, etc.)
   - `TopicItem`: Topic metadata (tid, title, post_time, replies count, etc.)
   - `ReplyItem`: Reply content with image URL support

4. **Pipelines** (`NGA_Scrapy/pipelines.py:1-225`)
   - `NgaPipeline`: Database storage using SQLAlchemy merge
   - `ImageDownloadPipeline`: Downloads images using Scrapy's ImagesPipeline
   - Handles transaction commits and rollbacks

5. **Middleware** (`NGA_Scrapy/middlewares.py:1-347`)
   - `PlaywrightMiddleware`: Browser pool management with Playwright
   - `BrowserPool`: Reusable browser instances with performance monitoring
   - Handles JavaScript-rendered pages and cookie management
   - Includes timeout handling and resource recycling

6. **Database Utils** (`NGA_Scrapy/utils/db_utils.py:1-28`)
   - `create_db_session()`: Creates SQLAlchemy session factory
   - Supports custom database URLs

7. **Email Notification System** (`scheduler/email_notifier.py:1-462`)
   - `EmailNotifier`: SMTP email sender with TLS support
   - `StatisticsCollector`: Aggregates spider statistics from JSON files
   - Supports HTML and plain text email formats
   - Handles statistics reports and error alerts

8. **Enhanced Scheduler** (`scheduler/run_scheduler.py:1-553`)
   - APScheduler-based with background execution
   - Real-time spider output logging with statistics parsing
   - Saves spider statistics to JSON files in `scheduler/stats/`
   - Graceful shutdown handling (SIGINT/SIGTERM)
   - Error monitoring with consecutive failure tracking

### Key Features

**Incremental Crawling** (`NGA_Scrapy/spiders/nga_spider.py:362-372`)
- Compares web timestamps with database records
- Skips topics/replies that aren't newer than stored data
- Supports multiple NGA time formats

**Browser Pool Management** (`NGA_Scrapy/middlewares.py:68-195`)
- Reuses Playwright browser instances for efficiency
- Pre-initializes configurable pool size (default 6)
- Includes performance statistics and monitoring

**Image Handling**
- Extracts image URLs from replies (`NGA_Scrapy/spiders/nga_spider.py:301-308`)
- Downloads and stores images locally (`NGA_Scrapy/pipelines.py:195-225`)
- Saves original URLs and local paths to database

**Email Notifications** (`scheduler/email_notifier.py:24-307`)
- **Statistics Reports**: Automated periodic reports (configurable, default every 3 days)
  - Crawl statistics (items scraped, pages crawled, duplication filtered)
  - Execution metrics (success rate, avg runtime, total executions)
  - Resource usage (download volume, average speed)
  - First report sent immediately after initial successful crawl
- **Error Alerts**: Real-time notifications for anomalies
  - Consecutive failures (default: 3+ failures)
  - Spider timeout (default: 60+ minutes)
  - High error rate (default: >20% in sliding window)
- HTML and plain text email formats with styling

**Statistics Tracking** (`scheduler/run_scheduler.py:319-357`)
- Saves spider statistics to timestamped JSON files (`scheduler/stats/spider_stats_*.json`)
- Aggregates metrics across time ranges
- Includes execution status, runtime, items scraped, response bytes
- Supports historical analysis and trending

**Enhanced Scheduler** (`scheduler/run_scheduler.py:114-251`)
- Real-time spider output monitoring and logging
- Parses Scrapy statistics from stdout and log files
- Graceful shutdown with signal handling
- Background execution with APScheduler
- Configurable via YAML (`scheduler/email_config.yaml`)

## Configuration

### Spider Settings (`NGA_Scrapy/settings.py`)

- `PLAYWRIGHT_POOL_SIZE`: Browser instance pool size (default: 6)
- `DOWNLOAD_TIMEOUT`: Global timeout (default: 20 seconds)
- `IMAGES_STORE`: Image storage path (default: `download_images`)
- `CONCURRENT_REQUESTS`: Concurrent requests (default: 16)
- `HTTPCACHE_ENABLED`: HTTP caching (default: False)
- `LOG_LEVEL`: Logging level (default: INFO)
- `LOG_FILE`: Log file path (default: `nga_spider.log`)
- `LOG_FILE_MAX_BYTES`: Log rotation size (default: 10MB)
- `LOG_FILE_BACKUP_COUNT`: Number of log backups (default: 5)

### Email Notification Settings (`scheduler/email_config.yaml`)

**SMTP Configuration:**
- `smtp_server`: SMTP server address (e.g., `smtp.qq.com`)
- `smtp_port`: SMTP port (587 for TLS, 465 for SSL)
- `username`: SMTP username
- `password`: SMTP password or app-specific password
- `from_email`: Sender email address
- `to_emails`: List of recipient email addresses
- `use_tls`: Enable TLS encryption (default: true)

**Notification Settings:**
- `enable_statistics_report`: Enable periodic statistics reports (default: true)
- `statistics_report_interval_days`: Report frequency in days (default: 3)
- `statistics_report_time`: Report time in HH:MM format (default: "09:00")
- `enable_error_alerts`: Enable error notifications (default: true)
- `consecutive_failures_threshold`: Alert after N consecutive failures (default: 3)
- `spider_timeout_minutes`: Timeout threshold in minutes (default: 60)
- `error_rate_alert.enabled`: Enable error rate alerts (default: true)
- `error_rate_alert.threshold_percent`: Error rate threshold percentage (default: 10)
- `error_rate_alert.time_window_minutes`: Time window for rate calculation (default: 30)

## Database Schema

- **user**: uid (PK), name, user_group, prestige, reg_date, history_re_num
- **topic**: tid (PK), title, poster_id (FK→user.uid), post_time, re_num, sampling_time, last_reply_date, partition
- **reply**: rid (PK), tid (FK→topic.tid), parent_rid (FK→reply.rid), content, recommendvalue, poster_id (FK→user.uid), post_time, image_urls (JSON), image_paths (JSON), sampling_time

## Development Notes

- User info scraping is currently commented out but can be re-enabled in `NGA_Scrapy/spiders/nga_spider.py:216-222` and `331-337`
- Time parsing supports multiple NGA formats (`NGA_Scrapy/spiders/nga_spider.py:374-400`)
- Cookie management via `cookies.txt` file, loaded in middleware (`NGA_Scrapy/middlewares.py:213-282`)
- Logs written to `nga_spider.log` with rotation (10MB max, 5 backups)
- Scheduler logs written to `scheduler/scheduler.log`
- Spider statistics saved to `scheduler/stats/spider_stats_YYYYMMDD_HHMMSS.json`
- Email notifications require valid SMTP credentials in `scheduler/email_config.yaml`
- For QQ Mail: Enable SMTP service and use app-specific password, not QQ password
- Statistics reports sent immediately after first successful crawl, then on configured schedule
- Scheduler handles graceful shutdown with Ctrl+C (SIGINT) or SIGTERM
- Background processes can be killed, but the scheduler will detect and skip if spider is still running
