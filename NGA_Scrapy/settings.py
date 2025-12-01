# setting.py
BOT_NAME = 'NGA_Scrapy'

SPIDER_MODULES = ['NGA_Scrapy.spiders']
NEWSPIDER_MODULE = 'NGA_Scrapy.spiders'

# 启用 中间件
DOWNLOADER_MIDDLEWARES = {
    'NGA_Scrapy.middlewares.PlaywrightMiddleware': 543,
    'NGA_Scrapy.custom_retry.CustomRetryMiddleware': 540,  # 使用自定义重试中间件
}

# 配置管道
ITEM_PIPELINES = {
    'NGA_Scrapy.pipelines.NgaPipeline': 300,
}

# 设置图片存储路径（使用相对路径，避免权限问题）
IMAGES_STORE = 'download_images'


PLAYWRIGHT_POOL_SIZE = 8  # 增加浏览器池大小，充分利用内存和CPU
DOWNLOAD_TIMEOUT = 25     # 稍微增加超时时间，避免频繁超时

# 遵守 robots.txt 规则
ROBOTSTXT_OBEY = False

# 配置日志
LOG_LEVEL = 'DEBUG'

# 日志配置
LOG_FILE = 'nga_spider.log'
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_FILE_BACKUP_COUNT = 5
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
LOG_DATEFORMAT = '%Y-%m-%d %H:%M:%S'

# 全局设置
# 已在上面定义：LOG_LEVEL, LOG_FILE, LOG_FORMAT, LOG_DATEFORMAT, LOG_FILE_MAX_BYTES, LOG_FILE_BACKUP_COUNT

# 优化并发配置，提高爬取速度
CONCURRENT_REQUESTS = 12  # 增加并发请求数，充分利用性能
CONCURRENT_REQUESTS_PER_DOMAIN = 6  # 每个域名的并发数
DOWNLOAD_DELAY = 0.5  # 减少延迟到0.5秒，平衡速度和稳定性
AUTOTHROTTLE_ENABLED = True  # 启用自动限速
AUTOTHROTTLE_START_DELAY = 0.5  # 初始延迟 0.5 秒
AUTOTHROTTLE_MAX_DELAY = 45  # 最大延迟 45 秒
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0  # 目标并发数提高
HTTPCACHE_ENABLED = False
HTTPCACHE_EXPIRATION_SECS = 186400  # 缓存 1 天
IMAGES_PIPELINE_MAX_SIZE = 1024*1024*5  # 限制最大图片尺寸(5MB)
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# 启用重试中间件，处理超时等临时性问题
RETRY_TIMES = 3  # 重试3次
# 包含超时状态码和常见的反爬状态码
# 403是IP被封，需要重试（可能是临时性的）
RETRY_HTTP_CODES = [403, 408, 440, 444, 460, 463, 494, 495, 496, 499, 500, 502, 503, 504]
RETRY_ENABLED = True

# 允许处理403错误（IP被封的情况会被重试）
HTTPERROR_ALLOW_ALL = True
HTTPERROR_ALLOWED_CODES = [200, 206, 301, 302, 403, 404, 500, 502, 503]

# 代理配置
PROXY_ENABLED = True  # 是否启用代理，默认为False（不使用代理）
PROXY_CONFIG_FILE = 'proxy_config.json'  # 代理配置文件路径

