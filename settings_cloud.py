# settings_cloud.py
# 专为2核4G云服务器优化的Scrapy配置
# 使用PostgreSQL数据库，支持高并发

from .settings import *

# 数据库配置 - PostgreSQL专用
# 注: 连接参数在 database_config.py 中配置

# ========================================
# 性能优化配置 (2核4G服务器)
# ========================================

# 浏览器池大小 (2核4G推荐: 3-4个实例)
# 2核CPU可以同时运行约3个浏览器实例
# 每个实例约占用200-250MB内存
PLAYWRIGHT_POOL_SIZE = 3

# 并发请求数 (2核4G推荐: 3-4个并发)
# 平衡CPU使用率和反爬策略
CONCURRENT_REQUESTS = 3
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# 下载延迟 (秒)
# 适度延迟避免被检测为机器人
DOWNLOAD_DELAY = 1.5

# 超时设置 (秒)
# 平衡响应速度和资源占用
DOWNLOAD_TIMEOUT = 20

# 自动限速配置
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

# ========================================
# 内存优化
# ========================================

# 禁用HTTP缓存以节省内存
HTTPCACHE_ENABLED = False

# 图片处理限制
IMAGES_PIPELINE_MAX_SIZE = 1024 * 1024 * 5  # 5MB
IMAGES_STORE = 'download_images'

# ========================================
# 重试和错误处理
# ========================================

# 重试配置
RETRY_TIMES = 3
RETRY_ENABLED = True

# 包含超时状态码和反爬状态码
RETRY_HTTP_CODES = [
    408,   # Request Timeout
    440,   # ??? (反爬常见)
    444,   # No Response
    460,   # ??? (反爬常见)
    463,   # ??? (反爬常见)
    494,   # Request header too large
    495,   # SSL Certificate Error
    496,   # SSL Certificate Required
    499,   # Client Closed Request
    500,   # Internal Server Error
    502,   # Bad Gateway
    503,   # Service Unavailable
    504,   # Gateway Timeout
]

# ========================================
# 日志配置
# ========================================

LOG_LEVEL = 'INFO'
LOG_FILE = 'nga_spider.log'
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_FILE_BACKUP_COUNT = 5
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
LOG_DATEFORMAT = '%Y-%m-%d %H:%M:%S'

# ========================================
# 中间件配置
# ========================================

DOWNLOADER_MIDDLEWARES = {
    'NGA_Scrapy.middlewares.PlaywrightMiddleware': 543,
    'NGA_Scrapy.custom_retry.CustomRetryMiddleware': 540,
}

ITEM_PIPELINES = {
    'NGA_Scrapy.pipelines.NgaPipeline': 300,
}

# ========================================
# 代理配置
# ========================================

PROXY_ENABLED = True
PROXY_CONFIG_FILE = 'proxy_config.json'

# ========================================
# 用户代理
# ========================================

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# ========================================
# 其他设置
# ========================================

ROBOTSTXT_OBEY = False

# ========================================
# 资源使用建议 (2核4G服务器)
# ========================================
"""
内存分配:
- PostgreSQL: ~300-400MB
- 3个浏览器实例: ~750MB
- Python运行时: ~200-300MB
- 系统预留: ~1GB
- 总计: ~2.2-2.5GB (在4GB内存限制内)

CPU使用:
- PostgreSQL: 10-20%
- 3个浏览器: 50-70%
- 爬虫逻辑: 10-20%
- 总计: 70-90% (合理使用率)

性能指标:
- 每小时可爬取: 3000-5000条数据
- 并发处理: 3个任务同时进行
- 内存峰值: ~2.5GB
- 平均响应: 1.5-2秒/页面

如果遇到性能问题，可以调整以下参数:
1. 降低 PLAYWRIGHT_POOL_SIZE 到 2
2. 降低 CONCURRENT_REQUESTS 到 2
3. 增加 DOWNLOAD_DELAY 到 2-3秒
"""
