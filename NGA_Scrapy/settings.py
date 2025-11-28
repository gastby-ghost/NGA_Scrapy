# setting.py
BOT_NAME = 'NGA_Scrapy'

SPIDER_MODULES = ['NGA_Scrapy.spiders']
NEWSPIDER_MODULE = 'NGA_Scrapy.spiders'

# 启用 中间件
DOWNLOADER_MIDDLEWARES = {
    'NGA_Scrapy.middlewares.PlaywrightMiddleware': 543,
}

# 配置管道
ITEM_PIPELINES = {
    'NGA_Scrapy.pipelines.ImageDownloadPipeline': 500,
    'NGA_Scrapy.pipelines.NgaPipeline': 300,
}

# 设置图片存储路径
IMAGES_STORE = '/download_images'


PLAYWRIGHT_POOL_SIZE = 6  # 根据CPU核心数调整（建议核心数×1.5）
DOWNLOAD_TIMEOUT = 20     # 全局超时时间

# 遵守 robots.txt 规则
ROBOTSTXT_OBEY = False

# 配置日志
LOG_LEVEL = 'INFO'

# 日志配置
LOG_FILE = 'nga_spider.log'
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_FILE_BACKUP_COUNT = 5
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
LOG_DATEFORMAT = '%Y-%m-%d %H:%M:%S'

custom_settings = {
    'LOG_LEVEL': LOG_LEVEL,
    'LOG_FILE': LOG_FILE,
    'LOG_FORMAT': LOG_FORMAT,
    'LOG_DATEFORMAT': LOG_DATEFORMAT,
    'LOG_FILE_MAX_BYTES': LOG_FILE_MAX_BYTES,
    'LOG_FILE_BACKUP_COUNT': LOG_FILE_BACKUP_COUNT,
    'CONCURRENT_REQUESTS': 16,  # 默认 16，根据目标网站承受能力调整
    'DOWNLOAD_DELAY': 0,     # 适当降低延迟
    'AUTOTHROTTLE_ENABLED': True,  # 启用自动限速
    'HTTPCACHE_ENABLED': True,
    'HTTPCACHE_EXPIRATION_SECS': 186400,  # 缓存 1 天
    'IMAGES_PIPELINE_MAX_SIZE': 1024*1024*5  # 限制最大图片尺寸(5MB)
}

