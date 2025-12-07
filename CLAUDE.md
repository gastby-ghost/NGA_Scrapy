# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NGA_Scrapy is a Scrapy-based web scraper for NGA forum (bbs.nga.cn) that crawls the water zone (fid=-7). It implements incremental crawling to only fetch new content, avoiding duplicates. The project uses Playwright for JavaScript rendering, SQLAlchemy for ORM, and supports scheduled crawling with email notifications.

## Quick Start

### Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Initialize database
python init_db.py
```

### Run Spider
```bash
# Basic crawling
scrapy crawl nga

# With custom database
scrapy crawl nga -a db_url="sqlite:///custom.db"

# Start scheduler
cd scheduler && python run_scheduler.py
```

## Core Architecture

### Spider Layer
- **nga_spider.py:1-405** - `NgaSpider` class with incremental crawling logic
- Compares timestamps to skip duplicates
- Parses topic lists, replies, and user info

### Data Layer
- **models.py:1-50** - SQLAlchemy models (User, Topic, Reply)
- **items.py:1-33** - Scrapy items for data structure
- **pipelines.py:1-225** - Database storage and image download pipelines

### Middleware
- **middlewares.py:1-347** - `PlaywrightMiddleware` with browser pool management
- **utils/proxy_manager.py** - Proxy rotation support
- **custom_retry.py** - Custom retry logic

### Scheduler
- **scheduler/run_scheduler.py:1-553** - APScheduler with email notifications
- **scheduler/email_notifier.py:1-462** - SMTP email system for stats and alerts
- Statistics saved to `scheduler/stats/spider_stats_*.json`

### Configuration
- **settings.py** - Playwright pool size, timeouts, concurrency
- **scheduler/email_config.yaml** - Email SMTP and notification settings

## Key Components

### Incremental Crawling (nga_spider.py:362-372)
```python
# Compares web timestamps with DB records
# Skips topics/replies that aren't newer
# Supports multiple NGA time formats
```

### Browser Pool (middlewares.py:68-195)
```python
# Pre-initializes browser instances (default: 2)
# Reuses pages for efficiency (single instance, multiple pages)
# Performance monitoring included
```

### Email Notifications (email_notifier.py:24-307)
- **Statistics Reports**: Periodic reports (default: every 3 days at 09:00)
- **Error Alerts**: Real-time notifications for failures, timeouts, high error rates
- **First Report**: Sent immediately after first successful crawl

## Common Development Tasks

### Debugging
```bash
# View spider logs
tail -f nga_spider.log

# View scheduler logs
tail -f scheduler/scheduler.log

# Check latest statistics
ls -lt scheduler/stats/ | head -5
```

### Testing Proxy Configuration
```bash
# Test proxy settings
python test_proxy_config.py

# Debug specific XPath
python debug_xpath.py
```

### Database Operations
```bash
# Initialize database
python init_db.py

# View database contents
sqlite3 nga.db ".tables"
```

## Development Notes

- **User scraping**: Commented out in `nga_spider.py:216-222,331-337`, can be re-enabled
- **Cookie management**: Load from `cookies.txt` in middleware
- **Time parsing**: Supports multiple NGA formats (nga_spider.py:374-400)
- **Logs**: Rotation at 10MB with 5 backups
- **Graceful shutdown**: Scheduler handles SIGINT/SIGTERM
- **Email**: QQ Mail requires app-specific password, not QQ password

## Database Schema

- **user**: uid (PK), name, user_group, prestige, reg_date, history_re_num
- **topic**: tid (PK), title, poster_id, post_time, re_num, sampling_time, last_reply_date, partition
- **reply**: rid (PK), tid, parent_rid, content, recommendvalue, poster_id, post_time, image_urls (JSON), image_paths (JSON), sampling_time

## Key Settings

### Spider (settings.py)
- `PLAYWRIGHT_POOL_SIZE`: Browser pool size (default: 2, optimized for single instance, multiple pages)
- `DOWNLOAD_TIMEOUT`: Request timeout (default: 30s)
- `CONCURRENT_REQUESTS`: Concurrent requests (default: 2, matches pool size)
- `IMAGES_STORE`: Image storage path

### Email (email_config.yaml)
- `smtp_server`, `smtp_port`: SMTP configuration
- `statistics_report_interval_days`: Report frequency (default: 3)
- `consecutive_failures_threshold`: Alert after N failures (default: 3)
- `spider_timeout_minutes`: Timeout threshold (default: 60)
