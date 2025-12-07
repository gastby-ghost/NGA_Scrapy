import scrapy
import json
import os
import time
import threading
import uuid
from queue import Queue, Empty
from typing import Optional, Dict, List, Callable, Any
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
from scrapy.exceptions import NotConfigured
from scrapy import signals
from NGA_Scrapy.utils.proxy_manager import get_proxy_manager
from NGA_Scrapy.utils.ban_detector import BanDetector
from NGA_Scrapy.utils.instance_manager import BrowserInstanceManager


# ========== 配置常量 ==========
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Linux"',
    'Upgrade-Insecure-Requests': '1'
}

BROWSER_ARGS = [
    '--disable-gpu',
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--disable-extensions',
    '--disable-infobars',
    '--disable-notifications',
]

DEFAULT_VIEWPORT = {'width': 1920, 'height': 1080}
REQUEST_TIMEOUT = 60
NAV_TIMEOUT = 15000
LOAD_TIMEOUT = 5000


# ========== 工具类 ==========
class PerformanceStats:
    """简化的性能统计工具类"""
    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self.reset()

    def reset(self):
        """重置统计数据"""
        with self._lock:
            self.request_count = 0
            self.success_count = 0
            self.failed_count = 0
            self.total_page_time = 0.0
            self.max_page_time = 0.0
            self.min_page_time = float('inf')
            self.browser_recycles = 0
            self.timeout_errors = 0

    def log_request(self, success: bool, duration: float):
        """记录请求统计"""
        with self._lock:
            self.request_count += 1
            if success:
                self.success_count += 1
                self.total_page_time += duration
                self.max_page_time = max(self.max_page_time, duration)
                self.min_page_time = min(self.min_page_time, duration)
            else:
                self.failed_count += 1

    def log_recycle(self):
        """记录实例回收"""
        with self._lock:
            self.browser_recycles += 1

    def log_timeout(self):
        """记录超时事件"""
        with self._lock:
            self.timeout_errors += 1

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            uptime = time.time() - self._start_time
            avg_time = (self.total_page_time / self.success_count) if self.success_count > 0 else 0

            return {
                'uptime': f"{uptime:.1f}s",
                'requests': self.request_count,
                'success_rate': f"{(self.success_count / self.request_count * 100):.2f}%" if self.request_count > 0 else "0%",
                'avg_page_time': f"{avg_time:.3f}s",
                'max_page_time': f"{self.max_page_time:.3f}s",
                'min_page_time': f"{self.min_page_time:.3f}s" if self.min_page_time != float('inf') else "N/A",
                'browser_recycles': self.browser_recycles,
                'timeout_errors': self.timeout_errors,
                'req_per_minute': f"{(self.request_count / (uptime / 60)):.2f}" if uptime > 0 else "N/A"
            }


# ========== Cookie管理 ==========
class CookieManager:
    """Cookie管理器 - 独立职责"""
    def __init__(self, logger):
        self.logger = logger
        self.cookies = None

    def load(self, cookies_file: str = 'cookies.txt') -> Optional[List[Dict]]:
        """加载并预处理cookies"""
        if not os.path.exists(cookies_file):
            self.logger.info(f"Cookies file not found: {cookies_file}")
            return None

        try:
            with open(cookies_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)

            processed = []
            for c in cookies:
                try:
                    expiry = c.get('expiry') or c.get('expirationDate')
                    if expiry is None:
                        expiry = int(time.time()) + 3600
                    elif isinstance(expiry, float):
                        expiry = int(expiry)

                    domain = c.get('domain', '.ngabbs.com')
                    if not domain.startswith('.'):
                        domain = f'.{domain}'

                    cookie_dict = {
                        'name': c['name'],
                        'value': c['value'],
                        'domain': domain,
                        'path': c.get('path', '/'),
                        'expires': expiry,
                        'httpOnly': c.get('httpOnly', False),
                        'secure': c.get('secure', False),
                        'sameSite': 'Lax'
                    }

                    processed.append({k: v for k, v in cookie_dict.items() if v is not None})
                except KeyError:
                    self.logger.warning(f"Skip invalid cookie: missing required field")
                    continue

            self.cookies = processed
            return processed
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in cookies file: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to load cookies: {e}")
            return None

    def save_if_updated(self, context):
        """检查并保存更新后的cookies"""
        try:
            current_cookies = context.cookies()
            nga_passport = next(
                (c for c in current_cookies if c['name'] == 'ngaPassportUid'),
                None
            )

            if nga_passport:
                old_passport = next(
                    (c for c in self.cookies if c['name'] == 'ngaPassportUid'),
                    None
                ) if self.cookies else None

                needs_update = (
                    not old_passport or
                    old_passport['value'] != nga_passport['value'] or
                    old_passport.get('expires', 0) != nga_passport.get('expires', 0)
                )

                if needs_update:
                    with open('cookies.txt', 'w', encoding='utf-8') as f:
                        json.dump(current_cookies, f, ensure_ascii=False, indent=2)

                    self.cookies = current_cookies
                    expires_time = time.strftime(
                        '%Y-%m-%d %H:%M:%S',
                        time.localtime(nga_passport['expires'])
                    )
                    self.logger.info(
                        f"✓ Updated ngaPassportUid: {nga_passport['value'][:20]}..., "
                        f"expires: {expires_time}"
                    )
        except Exception as e:
            self.logger.error(f"Auto-update cookies failed: {e}")


# ========== 页面获取器 ==========
class PageFetcher:
    """页面获取器 - 独立职责"""
    def __init__(self, logger):
        self.logger = logger

    def fetch(self, browser_pool: List, url: str, cookies: Optional[List],
              browser_index: int, referer: str = 'https://bbs.nga.cn/') -> Dict:
        """获取页面内容"""
        browser, context = browser_pool[browser_index % len(browser_pool)]
        page = context.new_page()

        try:
            self.logger.debug(f"Loading page: {url} (browser {browser_index})")

            if cookies:
                self.logger.debug(f"Setting {len(cookies)} cookies")
                context.clear_cookies()
                context.add_cookies(cookies)
                time.sleep(0.1)

            page.set_extra_http_headers({'Referer': referer})

            self.logger.debug(f"Navigating to: {url}")
            nav_start = time.time()
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            nav_time = time.time() - nav_start
            self.logger.debug(f"Navigation complete: {nav_time:.2f}s")

            page.wait_for_load_state("domcontentloaded", timeout=LOAD_TIMEOUT)

            return {
                'url': page.url,
                'content': page.content(),
                'success': True,
                'nav_time': nav_time
            }
        except Exception as e:
            self.logger.error(f"Page load failed: {url}, error: {type(e).__name__}: {str(e)}")
            raise
        finally:
            page.close()


# ========== Playwright工作线程 ==========
class PlaywrightWorker:
    """Playwright专用工作线程（负责浏览器池管理）"""
    def __init__(self, max_browsers: int, proxy_manager=None, logger=None):
        self.max_browsers = max_browsers
        self.proxy_manager = proxy_manager
        self.logger = logger or self._default_logger
        self._workers = []
        self._task_queue = Queue()
        self._result_map = {}
        self._condition = threading.Condition(threading.Lock())
        self._stop_event = threading.Event()
        self._initialized = threading.Event()
        self._browser_pool = []
        self._playwright = None
        self._start_worker()

    def _default_logger(self):
        import logging
        return logging.getLogger('PlaywrightWorker')

    def _start_worker(self):
        """启动工作线程"""
        worker = threading.Thread(
            target=self._playwright_worker_loop,
            name="PlaywrightWorker",
            daemon=False  # 非守护线程，确保正确关闭
        )
        worker.start()
        self._workers.append(worker)

        # 等待初始化完成
        self._initialized.wait(timeout=10)

    def _create_browser_pool(self):
        """在工作线程中创建浏览器池"""
        playwright = sync_playwright().start()

        for _ in range(self.max_browsers):
            browser = playwright.chromium.launch(
                headless=True,
                args=BROWSER_ARGS
            )

            context_kwargs = {
                'viewport': DEFAULT_VIEWPORT,
                'java_script_enabled': True,
                'ignore_https_errors': True,
                'permissions': [],
                'extra_http_headers': DEFAULT_HEADERS.copy()
            }

            if self.proxy_manager:
                proxy_dict = self.proxy_manager.get_random_proxy(mark_used=False)
                if proxy_dict and proxy_dict.get('proxy'):
                    proxy_server = proxy_dict['proxy']
                    proxy_config = {
                        'server': proxy_server,
                        'bypass': 'localhost;127.0.0.1;*.nga.cn;*.ngabbs.com'
                    }

                    if 'username' in proxy_dict and 'password' in proxy_dict:
                        proxy_config['username'] = proxy_dict['username']
                        proxy_config['password'] = proxy_dict['password']

                    context_kwargs['proxy'] = proxy_config
                    self.logger.debug(f"Using proxy: {proxy_server}")

            context = browser.new_context(**context_kwargs)
            self._browser_pool.append((browser, context))

        return playwright

    def _playwright_worker_loop(self):
        """Playwright工作线程主循环"""
        try:
            self.logger.info("Initializing Playwright worker...")
            self._playwright = self._create_browser_pool()
            self.logger.info(f"Browser pool initialized: {len(self._browser_pool)} instances")

            # 通知初始化完成
            self._initialized.set()

            # 工作线程主循环
            last_queue_check = time.time()
            while not self._stop_event.is_set():
                try:
                    request_id, task_func, args, kwargs, result_event = \
                        self._task_queue.get(timeout=0.1)

                    if self._stop_event.is_set():
                        if result_event:
                            result_event.set()
                        break

                    # 【诊断日志】记录任务队列状态
                    current_time = time.time()
                    if current_time - last_queue_check > 10:  # 每10秒记录一次
                        queue_size = self._task_queue.qsize()
                        self.logger.info(f"📊 [工作线程诊断] 任务队列大小: {queue_size}")
                        last_queue_check = current_time

                    task_start = time.time()
                    try:
                        # 在工作线程中执行任务
                        task_name = getattr(task_func, '__name__', 'unknown_task')
                        self.logger.debug(f"🔄 [工作线程] 开始执行任务: {task_name}")
                        
                        result = task_func(self._browser_pool, *args, **kwargs)
                        
                        task_duration = time.time() - task_start
                        self.logger.debug(f"✅ [工作线程] 任务完成: {task_name}, 耗时: {task_duration:.2f}s")
                        
                        with self._condition:
                            self._result_map[request_id] = ('success', result, None)
                    except Exception as e:
                        task_duration = time.time() - task_start
                        self.logger.error(f"❌ [工作线程] 任务失败: {task_name}, 耗时: {task_duration:.2f}s, 错误: {e}")
                        import traceback
                        with self._condition:
                            self._result_map[request_id] = ('error', None, (type(e), e, traceback.format_exc()))
                    finally:
                        with self._condition:
                            self._condition.notify_all()

                    if result_event:
                        result_event.set()
                except Empty:
                    continue
                except Exception as e:
                    self.logger.error(f"Worker error: {e}")

            # 清理资源
            self.logger.info("Closing browser instances...")
            for browser, context in self._browser_pool:
                try:
                    context.close()
                    browser.close()
                except Exception as e:
                    self.logger.warning(f"Error closing browser: {e}")

            if self._playwright:
                self._playwright.stop()

            self.logger.info("Playwright worker stopped")

        except Exception as e:
            self.logger.error(f"Playwright worker failed: {e}")
            self._initialized.set()  # 确保通知等待者
            raise

    def execute(self, task_func: Callable, *args, **kwargs):
        """在工作线程中执行任务"""
        if self._stop_event.is_set():
            raise InterruptedError("Playwright worker is shutting down")

        request_id = str(uuid.uuid4())
        result_event = threading.Event()
        task_name = getattr(task_func, '__name__', str(task_func))

        with self._condition:
            self._result_map[request_id] = None

        self._task_queue.put((request_id, task_func, args, kwargs, result_event))
        self.logger.debug(f"Task queued: {task_name}")

        # 等待结果
        if not result_event.wait(timeout=REQUEST_TIMEOUT):
            with self._condition:
                self._result_map.pop(request_id, None)
            raise TimeoutError(f"Task timeout: {task_name}")

        with self._condition:
            status, result, error = self._result_map.pop(request_id, ('timeout', None, 'Timeout'))

            if status == 'success':
                self.logger.debug(f"Task completed: {task_name}")
                return result
            elif status == 'error':
                exc_type, exc_value, _ = error
                self.logger.error(f"Task failed: {task_name}, {exc_type.__name__}: {exc_value}")
                raise exc_type(exc_value)
            else:
                self.logger.error(f"Task timeout: {task_name}")
                raise TimeoutError(f"Task timeout: {task_name}")

    def shutdown(self, timeout: int = 10):
        """关闭工作线程"""
        self.logger.info("Shutting down Playwright worker...")
        self._stop_event.set()

        for worker in self._workers:
            worker.join(timeout=timeout)

        self.logger.info("Playwright worker stopped")


# ========== 浏览器池 ==========
class BrowserPool:
    """浏览器连接池（使用PlaywrightWorker）"""
    def __init__(self, max_browsers: int = 4, proxy_manager=None, logger=None):
        self.max_browsers = max_browsers
        self.proxy_manager = proxy_manager
        self.logger = logger or self._default_logger
        self.stats = PerformanceStats()
        self._page_fetcher = PageFetcher(self.logger)
        self._playwright_worker = PlaywrightWorker(max_browsers, proxy_manager, logger)

    def _default_logger(self):
        import logging
        return logging.getLogger('BrowserPool')

    def fetch_page(self, url: str, cookies: Optional[List],
                   browser_index: int) -> Dict:
        """获取页面"""
        def _fetch_task(browser_pool):
            return self._page_fetcher.fetch(browser_pool, url, cookies, browser_index)

        return self._playwright_worker.execute(_fetch_task)

    def log_pool_status(self):
        """记录连接池状态"""
        stats = self.stats.get_stats()
        report = "\n".join([f"{k}: {v}" for k, v in stats.items()])
        self.logger.info(f"Performance stats:\n{report}")

    def close(self):
        """关闭浏览器池"""
        self.logger.info("Closing browser pool...")
        self._playwright_worker.shutdown()
        self.log_pool_status()
        self.logger.info("Browser pool closed")


# ========== Playwright中间件 ==========
class PlaywrightMiddleware:
    """优化的Playwright中间件"""
    def __init__(self):
        self.browser_pool = None
        self.logger = None
        self.cookie_manager = None
        self.proxy_manager = None
        self.ban_detector = None
        self.instance_manager = None
        self.last_stat_time = time.time()
        self._browser_index = 0
        self._failed_browsers = {}
        self._lock = threading.Lock()

    @classmethod
    def from_crawler(cls, crawler):
        if not crawler.settings.getbool('PLAYWRIGHT_ENABLED', True):
            raise NotConfigured('Playwright middleware not enabled')

        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def spider_opened(self, spider):
        """Spider启动处理"""
        self.logger = spider.logger
        self.logger.info("=" * 60)
        self.logger.info("Playwright middleware starting")
        self.logger.info("=" * 60)

        # 初始化Cookie管理器
        self.cookie_manager = CookieManager(self.logger)
        self.cookie_manager.load()

        # 初始化封禁检测器
        self.ban_detector = BanDetector(
            logger=self.logger,
            ban_threshold=spider.settings.getint('BAN_THRESHOLD', 3),
            recovery_time=spider.settings.getint('BAN_RECOVERY_TIME', 1800)
        )

        # 初始化实例管理器
        def replace_instance(failed_id: int) -> int:
            return self._replace_browser_instance(failed_id)

        self.instance_manager = BrowserInstanceManager(
            max_instances=spider.settings.getint('PLAYWRIGHT_POOL_SIZE', 4),
            ban_detector=self.ban_detector,
            replacement_callback=replace_instance,
            proxy_manager=self.proxy_manager,
            logger=self.logger
        )

        self.instance_manager.start()
        self.logger.info("Ban detection and instance manager started")

        # 初始化代理（如果启用）
        proxy_enabled = spider.settings.getbool('PROXY_ENABLED', False)
        if proxy_enabled:
            self._init_proxy(spider)
        else:
            self.logger.info("Proxy disabled")

        self.logger.info("=" * 60)

    def _init_proxy(self, spider):
        """初始化代理管理器"""
        try:
            self.logger.info("Initializing proxy manager...")
            self.proxy_manager = get_proxy_manager()
            proxies = self.proxy_manager.get_proxies(force_refresh=True)

            if proxies:
                self.logger.info(f"Loaded {len(proxies)} proxies")
            else:
                self.logger.warning("No proxies loaded")

            status = self.proxy_manager.get_pool_status()
            self.logger.info("Proxy pool status:")
            for key, value in status.items():
                self.logger.info(f"  - {key}: {value}")
        except FileNotFoundError:
            self.logger.error("Proxy config file not found")
            self.proxy_manager = None
        except ValueError as e:
            self.logger.error(f"Proxy config validation error: {e}")
            self.proxy_manager = None
        except Exception as e:
            self.logger.error(f"Proxy manager init failed: {e}")
            self.proxy_manager = None

    def spider_closed(self, spider, reason):
        """Spider关闭处理"""
        self.logger.info(f"Spider closed: {reason}")

        if self.instance_manager:
            self.instance_manager.stop()

        if self.browser_pool:
            self.browser_pool.close()

    def process_request(self, request, spider):
        """处理请求"""
        self.logger = spider.logger

        # 【新增调试】记录每个被调用的请求
        if 'read.php' in request.url:
            self.logger.debug(f"🔍 [Middleware] 收到请求: {request.url}, Priority: {request.priority}")
            # 【诊断日志】检查调度队列状态
            if hasattr(spider.crawler.engine, 'scheduler') and hasattr(spider.crawler.engine.scheduler, 'queue'):
                queue_size = len(spider.crawler.engine.scheduler.queue)
                self.logger.info(f"📊 [队列诊断] 当前调度队列长度: {queue_size}")

        # 统计报告
        if time.time() - self.last_stat_time > 300:
            if self.browser_pool:
                self.browser_pool.log_pool_status()
            if self.instance_manager:
                self.logger.info(self.instance_manager.get_status_report())
            self.last_stat_time = time.time()

        # 跳过图片请求
        if 'jpg' in request.url:
            return None

        try:
            # 确保浏览器池已初始化
            if not self.browser_pool:
                self.browser_pool = BrowserPool(
                    max_browsers=spider.settings.getint('PLAYWRIGHT_POOL_SIZE', 4),
                    proxy_manager=self.proxy_manager,
                    logger=self.logger
                )

            # 获取可用浏览器实例
            browser_index = self._select_browser_instance()
            if browser_index is None:
                self.logger.error("No available browser instances")
                return None

            # 尝试获取页面（最多3次）
            for attempt in range(3):
                try:
                    # 【诊断日志】记录页面获取开始
                    self.logger.info(f"🚀 [页面获取] 开始获取页面: {request.url[:80]}... (浏览器实例: {browser_index}, 尝试: {attempt + 1}/3)")
                    
                    start_time = time.time()
                    result = self.browser_pool.fetch_page(
                        request.url, self.cookie_manager.cookies, browser_index
                    )
                    response_time = time.time() - start_time

                    # 记录成功
                    self.browser_pool.stats.log_request(True, response_time)
                    if self.instance_manager:
                        self.instance_manager.report_success(browser_index, response_time)

                    self.logger.info(f"✅ [页面获取成功] {request.url[:80]}... ({response_time:.2f}s)")

                    return scrapy.http.HtmlResponse(
                        url=result['url'],
                        body=result['content'].encode('utf-8'),
                        encoding='utf-8',
                        request=request,
                        status=200  # 明确设置状态码
                    )

                except (PlaywrightTimeoutError, Exception) as e:
                    error_type = type(e).__name__

                    # 报告失败
                    is_banned = False
                    if self.instance_manager:
                        is_banned = self.instance_manager.report_failure(browser_index, e)

                    with self._lock:
                        self._failed_browsers[browser_index] = time.time()

                    self.logger.warning(
                        f"Browser {browser_index} failed (attempt {attempt + 1}/3): "
                        f"{error_type}: {str(e)[:100]}..."
                    )

                    if is_banned:
                        self.logger.warning(f"Browser {browser_index} banned, will be replaced")

                    # 选择下一个实例
                    browser_index = self._select_browser_instance()
                    if browser_index is None:
                        break

                    # 尝试下一个实例
                    continue

            # 所有尝试都失败
            self.browser_pool.stats.log_timeout()
            return scrapy.http.Response(
                url=request.url,
                status=408,
                body=b'',
                headers={'Retry-After': '30'}
            )

        except Exception as e:
            self.logger.error(f"Request processing failed: {e}")
            return None

    def _select_browser_instance(self) -> Optional[int]:
        """选择可用的浏览器实例"""
        pool_size = self.browser_pool.max_browsers if self.browser_pool else 1

        # 首先尝试使用实例管理器推荐的实例
        if self.instance_manager:
            selected = self.instance_manager.get_available_instance_id()
            if selected is not None and selected not in self.ban_detector.browser_instances:
                proxy_addr = None
                if self.proxy_manager:
                    try:
                        proxy_dict = self.proxy_manager.get_random_proxy(mark_used=False)
                        proxy_addr = proxy_dict.get('proxy') if proxy_dict else None
                    except:
                        pass
                self.instance_manager.register_instance(selected, proxy_addr)

                if not self.ban_detector.is_instance_banned(selected):
                    # 检查失败黑名单
                    with self._lock:
                        if selected not in self._failed_browsers or \
                           time.time() - self._failed_browsers[selected] >= 300:
                            return selected

        # 轮询选择
        for _ in range(pool_size):
            idx = self._browser_index % pool_size
            self._browser_index += 1

            # 检查封禁状态
            if self.ban_detector.is_instance_banned(idx):
                continue

            # 检查失败黑名单
            with self._lock:
                if idx in self._failed_browsers:
                    if time.time() - self._failed_browsers[idx] < 300:
                        continue
                    else:
                        del self._failed_browsers[idx]

            # 注册实例
            if self.instance_manager and idx not in self.ban_detector.browser_instances:
                proxy_addr = None
                if self.proxy_manager:
                    try:
                        proxy_dict = self.proxy_manager.get_random_proxy(mark_used=False)
                        proxy_addr = proxy_dict.get('proxy') if proxy_dict else None
                    except:
                        pass
                self.instance_manager.register_instance(idx, proxy_addr)

            return idx

        return None

    def _replace_browser_instance(self, failed_instance_id: int) -> Optional[int]:
        """替换失败的浏览器实例"""
        self.logger.info(f"Replacing browser instance {failed_instance_id}")
        return (failed_instance_id + 1000) % 10000

    def close_spider(self, spider):
        """关闭Spider"""
        if self.browser_pool:
            self.browser_pool.close()
