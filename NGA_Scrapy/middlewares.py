import scrapy
import json
import os
import time
import threading
import signal
import sys
from queue import Queue, Empty
from contextlib import contextmanager
from datetime import datetime
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from scrapy.exceptions import NotConfigured
from typing import Optional, Dict, List, Tuple
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message
import random
from concurrent.futures import ThreadPoolExecutor, Future
import uuid
from scrapy import signals
from NGA_Scrapy.utils.proxy_manager import get_proxy_manager

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
    """Playwright浏览器连接池（带性能监控）- 线程安全版本"""
    def __init__(self, max_browsers: int = 4, spider_logger=None, proxy_manager=None):
        self.max_browsers = max_browsers
        self.logger = spider_logger
        self.stats = PerformanceStats()
        self.proxy_manager = proxy_manager
        self._request_queue = Queue()
        self._result_map = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._playwright_thread = None
        self._stop_event = threading.Event()
        self._initialized = False
        self._init_condition = threading.Condition(self._lock)
        self._shutdown_handled = False

        # 启动Playwright工作线程（改为非守护线程以确保正确关闭）
        self._start_playwright_thread()

        # 等待初始化完成
        with self._init_condition:
            while not self._initialized:
                self._init_condition.wait(timeout=1)

    def _start_playwright_thread(self):
        """启动Playwright工作线程"""
        self._playwright_thread = threading.Thread(
            target=self._playwright_worker,
            name="PlaywrightWorker",
            daemon=False  # 改为非守护线程，确保正确关闭
        )
        self._playwright_thread.start()

    def _playwright_worker(self):
        """Playwright工作线程"""
        try:
            self.logger.info("正在初始化Playwright工作线程...")
            playwright = sync_playwright().start()
            self.logger.info("Playwright初始化完成")

            # 创建浏览器池
            browser_pool = []
            for _ in range(self.max_browsers):
                browser = playwright.chromium.launch(
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

                # 构建context参数
                context_kwargs = {
                    'viewport': {'width': 1920, 'height': 1080},
                    'java_script_enabled': True,
                    'ignore_https_errors': True,
                    'permissions': [],
                    'extra_http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
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
                }

                # 如果启用了代理，设置代理
                if self.proxy_manager:
                    self.logger.debug(f"🔍 获取随机代理 (池中有 {len(self.proxy_manager.proxy_pool)} 个代理)")
                    proxy_dict = self.proxy_manager.get_random_proxy()
                    if proxy_dict and proxy_dict.get('proxy'):
                        # 构建代理服务器地址
                        proxy_server = proxy_dict['proxy']
                        auth_info = ""
                        if 'username' in proxy_dict and 'password' in proxy_dict:
                            auth_info = f" (认证: {proxy_dict['username']})"

                        # 构建代理设置
                        proxy_config = {
                            'server': proxy_server,
                            'bypass': 'localhost;127.0.0.1;*.nga.cn;*.ngabbs.com'
                        }

                        # 如果有认证信息，添加认证
                        if 'username' in proxy_dict and 'password' in proxy_dict:
                            proxy_config['username'] = proxy_dict['username']
                            proxy_config['password'] = proxy_dict['password']

                        context_kwargs['proxy'] = proxy_config
                        self.logger.info(f"🌐 使用代理: {proxy_server}{auth_info}")
                    else:
                        self.logger.warning("⚠️ 未获取到可用代理，使用直连")

                context = browser.new_context(**context_kwargs)
                browser_pool.append((browser, context))

            self.logger.info(f"浏览器池初始化完成，共{len(browser_pool)}个实例")

            # 通知初始化完成
            with self._init_condition:
                self._initialized = True
                self._init_condition.notify_all()

            # 工作线程主循环
            while not self._stop_event.is_set():
                try:
                    # 从队列获取任务，使用较短的超时以便及时响应停止信号
                    request_id, task_func, args, kwargs, result_event = self._request_queue.get(timeout=0.1)

                    # 检查停止事件（避免在执行任务时被阻塞）
                    if self._stop_event.is_set():
                        # 处理队列中剩余的任务
                        if result_event:
                            result_event.set()
                        break

                    # 执行任务
                    try:
                        result = task_func(browser_pool, *args, **kwargs)
                        with self._condition:
                            self._result_map[request_id] = ('success', result, None)
                    except Exception as e:
                        # 保存异常对象及其类型信息
                        import traceback
                        with self._condition:
                            self._result_map[request_id] = ('error', None, (type(e), e, traceback.format_exc()))
                    finally:
                        with self._condition:
                            self._condition.notify_all()

                    # 通知任务完成
                    result_event.set()

                except Empty:
                    # 空队列，检查停止事件
                    continue
                except Exception as e:
                    self.logger.error(f"工作线程处理任务时出错: {str(e)}")

            # 处理队列中的剩余任务（快速清理）
            remaining_tasks = []
            while True:
                try:
                    request_id, task_func, args, kwargs, result_event = self._request_queue.get_nowait()
                    remaining_tasks.append((request_id, result_event))
                except Empty:
                    break

            # 标记这些任务为已取消
            for request_id, result_event in remaining_tasks:
                with self._condition:
                    self._result_map[request_id] = ('canceled', None, '任务被取消')
                self._condition.notify_all()
                if result_event:
                    result_event.set()

            # 清理资源
            self.logger.info("正在关闭浏览器实例...")
            for browser, context in browser_pool:
                try:
                    context.close()
                    browser.close()
                except Exception as e:
                    self.logger.warning(f"关闭资源时出错: {str(e)}")

            playwright.stop()
            self.logger.info("Playwright工作线程已退出")

        except Exception as e:
            self.logger.error(f"Playwright工作线程初始化失败: {str(e)}")
            with self._init_condition:
                self._initialized = True
                self._init_condition.notify_all()

    def _execute_in_playwright_thread(self, task_func, *args, **kwargs):
        """在Playwright工作线程中执行任务"""
        # 检查是否已收到停止信号
        if self._stop_event.is_set():
            self.logger.warning("⚠️ 浏览器池正在关闭，任务被中断")
            raise InterruptedError("浏览器池正在关闭，任务被中断")

        request_id = str(uuid.uuid4())
        result_event = threading.Event()
        task_name = getattr(task_func, '__name__', str(task_func))

        self.logger.debug(f"📥 接收任务: {task_name} (ID: {request_id})")

        with self._condition:
            self._result_map[request_id] = None

        # 添加任务到队列
        self._request_queue.put((request_id, task_func, args, kwargs, result_event))
        self.logger.debug(f"✅ 任务已添加到队列: {task_name} (ID: {request_id})")

        # 等待结果，使用较短的超时并检查停止事件
        timeout = 60
        wait_interval = 0.5  # 分段等待以便及时响应停止信号
        elapsed = 0

        while elapsed < timeout:
            # 检查停止事件
            if self._stop_event.is_set():
                self.logger.warning(f"⚠️ 任务执行期间收到停止信号，取消任务: {task_name} (ID: {request_id})")
                with self._condition:
                    self._result_map.pop(request_id, None)
                raise InterruptedError("浏览器池正在关闭，任务被中断")

            # 等待一小段时间
            if result_event.wait(timeout=wait_interval):
                break
            elapsed += wait_interval

            # 每10秒输出一次等待日志
            if elapsed > 0 and elapsed % 10 == 0:
                self.logger.debug(f"⏳ 任务仍在执行中: {task_name} (ID: {request_id})，已等待 {elapsed:.0f}s")

        with self._condition:
            status, result, error = self._result_map.pop(request_id, ('timeout', None, 'Timeout'))

            if status == 'success':
                self.logger.debug(f"✅ 任务执行成功: {task_name} (ID: {request_id})，耗时 {elapsed:.2f}s")
                return result
            elif status == 'canceled':
                self.logger.warning(f"❌ 任务被取消: {task_name} (ID: {request_id})")
                raise InterruptedError("任务被取消")
            elif status == 'error':
                # 重新抛出原始异常（保持异常类型）
                exc_type, exc_value, exc_traceback = error
                self.logger.error(f"❌ 任务执行失败: {task_name} (ID: {request_id})，错误: {exc_type.__name__}: {exc_value}")
                raise exc_type(exc_value)
            else:
                self.logger.error(f"⏰ 任务执行超时: {task_name} (ID: {request_id})，超时时间 {timeout}s")
                raise TimeoutError('任务执行超时')

    def execute(self, task_func, *args, **kwargs):
        """执行一个Playwright操作"""
        return self._execute_in_playwright_thread(task_func, *args, **kwargs)

    def log_pool_status(self):
        """记录当前连接池状态"""
        stats = self.stats.get_stats()
        status_report = "\n".join([f"{k}: {v}" for k, v in stats.items()])
        self.logger.info(f"性能统计报告:\n{status_report}")

    def close(self, force=False):
        """关闭所有资源

        Args:
            force: 是否强制立即关闭（用于信号处理）
        """
        self.logger.info("正在关闭浏览器池...")

        # 发送停止信号
        self._stop_event.set()

        if self._playwright_thread and self._playwright_thread.is_alive():
            # 增加超时时间以确保优雅关闭
            timeout = 5 if force else 30
            self.logger.info(f"等待工作线程结束，超时时间: {timeout}秒...")

            # 发送SIGINT到工作线程以加速关闭
            if force and hasattr(signal, 'pthread_sigmask'):
                try:
                    # 尝试中断队列等待
                    import ctypes
                    ctypes.pythonapi.PyThread_set_thread_name(
                        self._playwright_thread.ident, "PlaywrightWorker"
                    )
                except:
                    pass

            self._playwright_thread.join(timeout=timeout)

            # 检查线程是否仍在运行
            if self._playwright_thread.is_alive():
                self.logger.warning("工作线程未能在超时时间内结束，强制关闭")
                # 强制关闭浏览器实例
                # 注意：由于浏览器实例在工作线程中，这里只能记录警告

        self.log_pool_status()
        self.logger.info("浏览器池已关闭")


class PlaywrightMiddleware:
    def __init__(self):
        self.browser_pool = None
        self.logger = None
        self.cookies = None
        self.proxy_manager = None
        self.last_stat_time = time.time()
        self._browser_index = 0  # 用于轮询选择浏览器实例

    @classmethod
    def from_crawler(cls, crawler):
        if not crawler.settings.getbool('PLAYWRIGHT_ENABLED', True):
            raise NotConfigured('Playwright middleware not enabled')

        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def spider_opened(self, spider):
        """Spider启动时的处理"""
        self.logger = spider.logger
        self.logger.info("=" * 60)
        self.logger.info("🚀 Playwright中间件已启动，信号处理器已注册")
        self.logger.info("=" * 60)

        # 检查是否启用代理
        proxy_enabled = spider.settings.getbool('PROXY_ENABLED', False)
        self.logger.info(f"🔍 检查代理设置: PROXY_ENABLED = {proxy_enabled}")

        if proxy_enabled:
            try:
                self.logger.info("🔧 正在初始化代理管理器...")
                self.proxy_manager = get_proxy_manager()
                self.logger.info("✅ 代理管理器已初始化")

                # 获取初始代理列表
                self.logger.info("🔄 正在获取初始代理列表...")
                proxies = self.proxy_manager.get_proxies(force_refresh=True)

                if proxies:
                    self.logger.info(f"✅ 成功加载 {len(proxies)} 个代理")
                    self.logger.info(f"📋 代理列表: {', '.join(proxies[:5])}")
                    if len(proxies) > 5:
                        self.logger.info(f"   ... 等共 {len(proxies)} 个代理")
                else:
                    self.logger.warning("⚠️ 未获取到任何代理")

                # 显示代理池状态
                status = self.proxy_manager.get_pool_status()
                self.logger.info("📊 代理池初始状态:")
                for key, value in status.items():
                    self.logger.info(f"   - {key}: {value}")

                self.logger.info("=" * 60)

            except FileNotFoundError as e:
                self.logger.error("=" * 60)
                self.logger.error(f"❌ 代理配置文件错误: {e}")
                self.logger.error("请确保 proxy_config.json 文件存在且配置正确")
                self.logger.error("=" * 60)
                self.proxy_manager = None

            except ValueError as e:
                self.logger.error("=" * 60)
                self.logger.error(f"❌ 代理配置验证错误: {e}")
                self.logger.error("请检查配置文件中的 trade_no 和 api_key 是否正确")
                self.logger.error("=" * 60)
                self.proxy_manager = None

            except Exception as e:
                self.logger.error("=" * 60)
                self.logger.error(f"❌ 代理管理器初始化失败: {str(e)}")
                self.logger.error(f"错误类型: {type(e).__name__}")
                self.logger.error("=" * 60)
                self.proxy_manager = None
        else:
            self.logger.info("ℹ️  代理未启用 (PROXY_ENABLED = False)")
            self.logger.info("=" * 60)

    def spider_closed(self, spider, reason):
        """Spider关闭时的处理"""
        self.logger.info(f"Spider关闭原因: {reason}")
        if self.browser_pool:
            self.logger.info("正在通过信号处理器关闭浏览器池...")
            self.browser_pool.close()


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

    def _save_cookies_if_updated(self, context):
        """
        检查并保存更新后的cookies
        这个方法会在每次成功访问页面后被调用，自动更新ngaPassportUid等cookies
        """
        try:
            # 从当前context获取所有cookies
            current_cookies = context.cookies()

            # 查找ngaPassportUid（短效cookie）
            nga_passport = next(
                (c for c in current_cookies if c['name'] == 'ngaPassportUid'),
                None
            )

            if nga_passport:
                # 查找旧的ngaPassportUid
                old_nga_passport = next(
                    (c for c in self.cookies if c['name'] == 'ngaPassportUid'),
                    None
                )

                # 如果旧的不存在，或值/过期时间不同，则需要更新
                needs_update = (
                    not old_nga_passport or
                    old_nga_passport['value'] != nga_passport['value'] or
                    old_nga_passport.get('expires', 0) != nga_passport.get('expires', 0)
                )

                if needs_update:
                    # 保存所有cookies到文件
                    with open('cookies.txt', 'w', encoding='utf-8') as f:
                        json.dump(current_cookies, f, ensure_ascii=False, indent=2)

                    # 更新内存中的cookies缓存
                    self.cookies = current_cookies

                    # 记录日志
                    expires_time = time.strftime(
                        '%Y-%m-%d %H:%M:%S',
                        time.localtime(nga_passport['expires'])
                    )
                    self.logger.info(
                        f"✓ 已自动更新 ngaPassportUid - "
                        f"新值: {nga_passport['value'][:20]}..., "
                        f"过期时间: {expires_time}"
                    )

        except Exception as e:
            self.logger.error(f"自动更新cookies失败: {e}")

    def process_request(self, request, spider):
        if not self.logger:
            self.logger = spider.logger

        if not self.cookies:
            self._load_cookies()

        if not self.browser_pool:
            self.browser_pool = BrowserPool(
                max_browsers=spider.settings.getint('PLAYWRIGHT_POOL_SIZE', 4),
                spider_logger=spider.logger,
                proxy_manager=self.proxy_manager
            )

        # 每小时输出一次统计报告
        if time.time() - self.last_stat_time > 3600:
            self.browser_pool.log_pool_status()
            self.last_stat_time = time.time()

        if 'jpg' in request.url:
            return None

        try:
            # 定义浏览器任务函数
            def _fetch_page(browser_pool, url, cookies, browser_index):
                browser, context = browser_pool[browser_index % len(browser_pool)]
                page = context.new_page()

                try:
                    self.logger.debug(f"🌐 准备加载页面: {url} (使用浏览器 {browser_index % len(browser_pool)})")

                    if cookies:
                        self.logger.debug(f"🍪 设置 Cookies，共 {len(cookies)} 个")
                        # 先清除旧的 cookies
                        context.clear_cookies()
                        # 添加新的 cookies
                        context.add_cookies(cookies)
                        # 等待一小段时间确保 cookies 设置完成
                        time.sleep(0.1)

                    # 设置 Referer 头部，模拟从首页跳转
                    self.logger.debug(f"📋 设置 Referer 头部")
                    page.set_extra_http_headers({
                        'Referer': 'https://bbs.nga.cn/'
                    })

                    self.logger.debug(f"🚀 开始导航到页面...")
                    nav_start = time.time()
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    nav_time = time.time() - nav_start
                    self.logger.debug(f"✅ 页面导航完成，耗时: {nav_time:.2f}s，URL: {page.url}")

                    alert_start = time.time()
                    self._handle_alert(page)
                    alert_time = time.time() - alert_start

                    load_start = time.time()
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                    load_time = time.time() - load_start
                    self.logger.debug(f"⏱️ 页面加载完成: nav={nav_time:.2f}s, alert={alert_time:.2f}s, wait={load_time:.2f}s")

                    # 【关键改进】在返回前自动更新cookies
                    self.logger.debug(f"💾 更新 Cookies...")
                    self._save_cookies_if_updated(context)

                    self.logger.debug(f"📄 页面内容获取完成，字节数: {len(page.content())}")

                    return {
                        'url': page.url,
                        'content': page.content(),
                        'success': True
                    }
                except Exception as e:
                    self.logger.error(f"❌ 页面加载失败: {url}，错误: {type(e).__name__}: {str(e)}")
                    raise
                finally:
                    self.logger.debug(f"🔒 关闭页面实例")
                    page.close()

            # 轮询选择浏览器实例
            browser_index = self._browser_index
            self._browser_index = (self._browser_index + 1) % 1000000  # 防止溢出

            # 在Playwright工作线程中执行页面获取
            result = self.browser_pool.execute(
                _fetch_page,
                request.url,
                self.cookies,
                browser_index
            )

            self.browser_pool.stats.log_request(True, 1.0)

            return scrapy.http.HtmlResponse(
                url=result['url'],
                body=result['content'].encode('utf-8'),
                encoding='utf-8',
                request=request
            )
        except PlaywrightTimeoutError as e:
            # 超时错误，转换为可重试的响应（不显示为错误）
            self.browser_pool.stats.log_timeout()
            # 每100次超时输出一次统计
            if self.browser_pool.stats.timeout_errors % 100 == 0:
                self.browser_pool.log_pool_status()
            # 返回 408 状态码，让 RetryMiddleware 自动重试
            return scrapy.http.Response(
                url=request.url,
                status=408,  # Request Timeout
                body=b'',
                headers={'Retry-After': '30'}  # 建议 30 秒后重试
            )
        except Exception as e:
            # 其他错误，记录日志
            spider.logger.warning(f"Playwright请求处理失败（非超时）: {str(e)}")
            self.browser_pool.stats.log_request(False, 0)
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

