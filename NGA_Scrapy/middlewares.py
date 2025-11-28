import scrapy
import json
import os
import time
import threading
from queue import Queue, Empty
from contextlib import contextmanager
from datetime import datetime
from playwright.sync_api import sync_playwright
from scrapy.exceptions import NotConfigured
from typing import Optional, Dict, List, Tuple
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message
import random

class PerformanceStats:
    """性能统计工具类"""
    def __init__(self):
        self.start_time = time.time()
        self.request_count = 0
        self.success_count = 0
        self.failed_count = 0
        self.total_page_time = 0
        self.max_page_time = 0
        self.min_page_time = float('inf')
        self.browser_recycles = 0
        self.timeout_errors = 0
        self._lock = threading.Lock()

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
        """获取当前统计信息"""
        avg_time = (self.total_page_time / self.success_count) if self.success_count > 0 else 0
        uptime = time.time() - self.start_time
        return {
            'uptime': uptime,
            'requests': self.request_count,
            'success_rate': f"{(self.success_count / self.request_count * 100):.2f}%" if self.request_count > 0 else "0%",
            'avg_page_time': f"{avg_time:.3f}s",
            'max_page_time': f"{self.max_page_time:.3f}s",
            'min_page_time': f"{self.min_page_time:.3f}s" if self.min_page_time != float('inf') else "N/A",
            'browser_recycles': self.browser_recycles,
            'timeout_errors': self.timeout_errors,
            'req_per_minute': f"{(self.request_count / (uptime / 60)):.2f}" if uptime > 0 else "N/A"
        }

class BrowserPool:
    """Playwright浏览器连接池（带性能监控）"""
    def __init__(self, max_browsers: int = 4, spider_logger=None):
        self.max_browsers = max_browsers
        self.logger = spider_logger
        self._pool = Queue(maxsize=max_browsers)
        self._lock = threading.Lock()
        self._active_count = 0
        self.playwright = sync_playwright().start()
        self.stats = PerformanceStats()
        
        # 预初始化浏览器实例
        for _ in range(max_browsers):
            self._add_browser_instance()

    def _add_browser_instance(self):
        """创建新的浏览器实例并加入池中"""
        start_time = time.time()
        with self._lock:
            if self._active_count >= self.max_browsers:
                return

            try:
                browser = self.playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-gpu',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-extensions',
                        '--disable-infobars',
                        '--disable-notifications',
                    ]
                )
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    java_script_enabled=True,
                    ignore_https_errors=True,
                    permissions=[],
                    extra_http_headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                )
                self._pool.put((browser, context))
                self._active_count += 1
                duration = time.time() - start_time
                self.logger.debug(
                    f"新增浏览器实例(耗时{duration:.2f}s)，当前池大小: {self._active_count}/{self.max_browsers}"
                )
            except Exception as e:
                self.logger.error(f"创建浏览器实例失败: {str(e)}")
                raise

    @contextmanager
    def acquire(self, cookies: Optional[List[Dict]] = None):
        """获取浏览器资源上下文管理器（带性能监控）"""
        browser, context = None, None
        start_time = time.time()
        try:
            try:
                browser, context = self._pool.get(timeout=30)
                page = context.new_page()
                
                if cookies:
                    context.clear_cookies()
                    context.add_cookies(cookies)
                
                yield page
                self.stats.log_request(True, time.time() - start_time)
            except Empty:
                self.stats.log_timeout()
                self.logger.warning("获取浏览器实例超时，当前池状态: "
                                  f"{self._active_count}/{self.max_browsers} 活跃")
                raise TimeoutError("获取浏览器实例超时，请检查资源是否充足")
            except Exception as e:
                self.stats.log_request(False, time.time() - start_time)
                self.logger.error(f"使用浏览器资源时出错: {str(e)}")
                raise
        finally:
            try:
                if 'page' in locals() and page and not page.is_closed():
                    page.close()
            except Exception as e:
                self.logger.warning(f"关闭页面时出错: {str(e)}")
            
            if browser and context:
                self._pool.put((browser, context))
                # 记录资源等待时间
                wait_duration = time.time() - start_time
                if wait_duration > 1:  # 只记录显著等待
                    self.logger.debug(f"资源等待时间: {wait_duration:.2f}s")

    def _reinit_instance(self, browser, context):
        """重建问题实例（带监控）"""
        start_time = time.time()
        try:
            if context:
                context.close()
            if browser:
                browser.close()
        except Exception as e:
            self.logger.warning(f"关闭问题实例时出错: {str(e)}")
        
        self._add_browser_instance()
        self.stats.log_recycle()
        self.logger.warning(f"实例重建完成，耗时: {time.time() - start_time:.2f}s")

    def log_pool_status(self):
        """记录当前连接池状态"""
        stats = self.stats.get_stats()
        status_report = "\n".join([f"{k}: {v}" for k, v in stats.items()])
        self.logger.info(f"性能统计报告:\n{status_report}")

    def close(self):
        """关闭所有资源并输出最终报告"""
        start_time = time.time()
        while not self._pool.empty():
            browser, context = self._pool.get_nowait()
            try:
                context.close()
                browser.close()
            except Exception as e:
                self.logger.warning(f"关闭资源时出错: {str(e)}")
        
        self.playwright.stop()
        self.log_pool_status()
        self.logger.info(f"资源清理完成，耗时: {time.time() - start_time:.2f}s")


class PlaywrightMiddleware:
    def __init__(self):
        self.browser_pool = None
        self.logger = None
        self.cookies = None
        self.last_stat_time = time.time()

    @classmethod
    def from_crawler(cls, crawler):
        if not crawler.settings.getbool('PLAYWRIGHT_ENABLED', True):
            raise NotConfigured('Playwright middleware not enabled')
        
        middleware = cls()
        return middleware


    def _load_cookies(self) -> None:
        """
        预加载cookies（带性能监控和错误处理）
        功能特性：
        1. 文件存在性检查
        2. JSON格式验证
        3. 字段兼容性处理
        4. 性能监控
        5. 详细的错误处理
        """
        start_time = time.time()
        cookies_file = 'cookies.txt'
        
        # 1. 文件检查
        if not os.path.exists(cookies_file):
            self.logger.info(f"Cookies文件未找到: {cookies_file}")
        
        try:
            # 2. 文件读取和JSON解析
            with open(cookies_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            
            # 3. 性能监控点
            parse_time = time.time()
            
            # 4. Cookies转换处理
            processed_cookies = []
            for c in cookies:
                try:
                    # 处理expiry/expirationDate字段
                    expiry = c.get('expiry') or c.get('expirationDate')
                    if expiry is None:
                        expiry = int(time.time()) + 3600  # 默认1小时过期
                    elif isinstance(expiry, float):
                        expiry = int(expiry)
                    
                    # 处理domain字段
                    domain = c.get('domain', '.ngabbs.com')
                    if not domain.startswith('.'):
                        domain = f'.{domain}'
                    
                    # 构建标准cookie字典
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
                    
                    # 移除None值
                    cookie_dict = {k: v for k, v in cookie_dict.items() if v is not None}
                    processed_cookies.append(cookie_dict)
                
                except KeyError as e:
                    self.logger.info(f"[警告] 忽略无效cookie条目，缺少必要字段: {e}")
                    continue
            
            # 5. 设置处理后的cookies
            self.cookies = processed_cookies
            
            
        except json.JSONDecodeError as e:
            self.logger.info(f"Cookies文件JSON格式错误: {e}")
        except Exception as e:
            self.logger.info(f"加载cookies时发生未知错误: {e}")

    def process_request(self, request, spider):
        if not self.logger:
            self.logger = spider.logger

        if not self.cookies:
            self._load_cookies()

        if not self.browser_pool:
            self.browser_pool = BrowserPool(
                max_browsers=spider.settings.getint('PLAYWRIGHT_POOL_SIZE', 4),
                spider_logger=spider.logger
            )
        
        # 每小时输出一次统计报告
        if time.time() - self.last_stat_time > 3600:
            self.browser_pool.log_pool_status()
            self.last_stat_time = time.time()
        
        if 'jpg' in request.url:
            a=1

        try:
            with self.browser_pool.acquire(cookies=self.cookies) as page:
                nav_start = time.time()
                page.goto(request.url, wait_until="domcontentloaded", timeout=15000)
                nav_time = time.time() - nav_start
                
                alert_start = time.time()
                self._handle_alert(page)
                alert_time = time.time() - alert_start
                
                load_start = time.time()
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                load_time = time.time() - load_start
                
                self.logger.debug(
                    f"页面加载分解耗时 - 导航: {nav_time:.2f}s, "
                    f"弹窗处理: {alert_time:.2f}s, "
                    f"等待完成: {load_time:.2f}s"
                )
                
                return scrapy.http.HtmlResponse(
                    url=page.url,
                    body=page.content().encode('utf-8'),
                    encoding='utf-8',
                    request=request
                )
        except Exception as e:
            spider.logger.error(f"Playwright请求处理失败: {str(e)}")
            return None

    def _handle_alert(self, page):
        """处理弹窗（带性能监控）"""
        def handle_dialog(dialog):
            start_time = time.time()
            dialog.accept()
            self.logger.debug(f"弹窗处理耗时: {time.time() - start_time:.4f}s - {dialog.message[:50]}...")
        
        page.on('dialog', handle_dialog)

    def close_spider(self, spider):
        if self.browser_pool:
            self.browser_pool.close()

