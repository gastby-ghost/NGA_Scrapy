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


PLAYWRIGHT_POOL_SIZE = 8  # 大幅增加浏览器池大小，应对两阶段优化的高并发
DOWNLOAD_TIMEOUT = 30     # 增加超时时间，应对高负载

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

# 优化并发配置，平衡性能和稳定性（避免过载）
# 降低并发数到6，与浏览器池大小匹配，避免队列拥塞
CONCURRENT_REQUESTS = 6  # 与浏览器池大小匹配
CONCURRENT_REQUESTS_PER_DOMAIN = 6  # 每个域名的并发数
DOWNLOAD_DELAY = 0.3  # 适度延迟，平衡速度和稳定性
AUTOTHROTTLE_ENABLED = True  # 启用自动限速
AUTOTHROTTLE_START_DELAY = 0.3  # 初始延迟
AUTOTHROTTLE_MAX_DELAY = 30  # 最大延迟，给系统更多恢复时间
AUTOTHROTTLE_TARGET_CONCURRENCY = 6.0  # 目标并发数，更保守的设置
HTTPCACHE_ENABLED = False
HTTPCACHE_EXPIRATION_SECS = 186400  # 缓存 1 天
IMAGES_PIPELINE_MAX_SIZE = 1024*1024*5  # 限制最大图片尺寸(5MB)
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# 启用重试中间件，处理超时等临时性问题
RETRY_TIMES = 2  # 减少重试次数，避免过多重试加剧拥堵
# 包含超时状态码和常见的反爬状态码
# 403是IP被封，需要重试（可能是临时性的）
RETRY_HTTP_CODES = [403, 408, 440, 444, 460, 463, 494, 495, 496, 499, 500, 502, 503, 504]
RETRY_ENABLED = True

# 新增：优化调度器配置，处理大量请求
SCHEDULER_PRIORITY_QUEUE = 'scrapy.pqueues.ScrapyPriorityQueue'
DOWNLOAD_MAXSIZE = 1073741824  # 1GB，允许更大的响应
COOKIES_ENABLED = True  # 确保cookies功能开启
DUPEFILTER_CLASS = 'scrapy.dupefilters.RFPDupeFilter'  # 使用标准去重器

# 允许处理403错误（IP被封的情况会被重试）
HTTPERROR_ALLOW_ALL = True
HTTPERROR_ALLOWED_CODES = [200, 206, 301, 302, 403, 404, 500, 502, 503]

# 代理配置
PROXY_ENABLED = True  # 是否启用代理，默认为False（不使用代理）
PROXY_CONFIG_FILE = 'proxy_config.json'  # 代理配置文件路径

# 封禁检测和实例管理配置
BAN_THRESHOLD = 3  # 触发封禁的失败次数阈值
BAN_RECOVERY_TIME = 1800  # 封禁恢复时间（秒），默认30分钟
INSTANCE_MONITOR_ENABLED = True  # 是否启用实例监控和自动管理

