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

Default runs every 30 minutes.

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

**Scheduler** (`scheduler/run_scheduler.py:1-29`)
- APScheduler-based periodic execution
- Default interval: 30 minutes
- Uses subprocess to run scrapy command

## Configuration

Key settings in `NGA_Scrapy/settings.py:22-51`:

- `PLAYWRIGHT_POOL_SIZE`: Browser instance pool size (default: 6)
- `DOWNLOAD_TIMEOUT`: Global timeout (default: 20 seconds)
- `IMAGES_STORE`: Image storage path (default: `/download_images`)
- `CONCURRENT_REQUESTS`: Concurrent requests (default: 16)
- `HTTPCACHE_ENABLED`: HTTP caching enabled (default: True)

## Database Schema

- **user**: uid (PK), name, user_group, prestige, reg_date, history_re_num
- **topic**: tid (PK), title, poster_id (FK→user.uid), post_time, re_num, sampling_time, last_reply_date, partition
- **reply**: rid (PK), tid (FK→topic.tid), parent_rid (FK→reply.rid), content, recommendvalue, poster_id (FK→user.uid), post_time, image_urls (JSON), image_paths (JSON), sampling_time

## Development Notes

- User info scraping is currently commented out but can be re-enabled in `NGA_Scrapy/spiders/nga_spider.py:216-222` and `331-337`
- Time parsing supports multiple NGA formats (`NGA_Scrapy/spiders/nga_spider.py:374-400`)
- Cookie management via `cookies.txt` file, loaded in middleware (`NGA_Scrapy/middlewares.py:213-282`)
- Logs written to `nga_spider.log` with rotation (10MB max, 5 backups)
