# # nga_spider.py
# 以下是NGA爬虫代码的功能和特性总结，基于这些信息可以完整还原代码：

# ### 1. 核心功能
# - **主题爬取**：爬取NGA论坛水区(fid=-7)前10页的主题列表
# - **回复爬取**：对每个主题爬取其所有回复内容
# - **用户信息爬取**：获取发帖用户的基本信息
# - **增量爬取**：通过比较数据库中的最后回复时间，只爬取新内容

# ### 2. 主要特性

# #### 数据库集成
# - 使用SQLAlchemy ORM进行数据库操作
# - 支持从命令行传入数据库URL(db_url参数)
# - 使用scoped_session确保线程安全
# - 自动初始化/关闭数据库连接
# - 缓存主题最后回复时间减少数据库查询

# #### 增量爬取机制
# - 比较网页时间与数据库时间(`is_newer`方法)
# - 跳过已存在的旧回复
# - 支持多种NGA时间格式解析(`_parse_nga_time`方法)

# #### 数据提取
# - **主题信息**：标题、ID、发帖人、发帖时间、回复数、最后回复时间、分区
# - **回复信息**：内容、推荐值、回复时间、父回复ID
# - **用户信息**：用户组、注册日期等

# #### 性能优化
# - 主题列表页并行爬取(10页并发)
# - 回复分页自动处理
# - 数据库查询结果缓存
# - 跳过无新回复的主题

# #### 错误处理
# - 全面的异常捕获(SQLAlchemyError等)
# - 时间解析失败处理
# - 数据库连接失败处理
# - 详细的日志记录

# #### 代码结构
# - 使用Scrapy标准Spider结构
# - 模块化设计(数据库操作分离)
# - 清晰的回调方法链:
#   `parse → parse_topic_list → parse_replies`

# ### 3. 关键方法

# 1. **数据库相关**:
#    - `_init_db`: 初始化数据库连接
#    - `get_last_reply_from_db`: 查询主题最后回复时间
#    - `close`: 清理资源

# 2. **爬取逻辑**:
#    - `parse`: 入口点，生成主题列表页请求
#    - `parse_topic_list`: 解析主题列表
#    - `parse_replies`: 解析回复内容及分页
#    - `parse_user`: 解析用户信息(当前被注释)

# 3. **工具方法**:
#    - `is_newer`: 时间比较
#    - `_parse_nga_time`: 时间格式解析
#    - `_now_time`: 获取当前时间

# ### 4. 数据模型
# 使用三个Scrapy Item:
# - `TopicItem`: 存储主题信息
# - `ReplyItem`: 存储回复信息
# - `UserItem`: 存储用户信息

# ### 5. 配置参数
# - `name = 'nga'`
# - `allowed_domains = ['bbs.nga.cn']`
# - `start_urls`: 水区首页
# - 支持从命令行传入`db_url`

# ### 6. 性能考虑
# - 数据库会话管理(scoped_session)
# - 减少不必要的请求(通过时间比较)
# - 并发爬取多个主题页
# - 缓存机制减少数据库查询

# ### 7. 待优化点
# - 用户信息爬取当前被注释
# - 可添加请求延迟控制
# - 可增加代理支持
# - 可添加更详细的统计信息

import re
import scrapy
from scrapy import Request
from ..items import TopicItem, ReplyItem, UserItem
from urllib.parse import parse_qs, urljoin
import time
from datetime import datetime
from sqlalchemy.orm import scoped_session
from sqlalchemy.exc import SQLAlchemyError
from ..models import Base
from ..utils.monitoring import get_monitor, record_batch_query
from ..utils.cache_manager import get_cache_manager
from ..utils.query_optimizer import QueryOptimizer
import psutil
import os

class NgaSpider(scrapy.Spider):
    name = 'nga'
    allowed_domains = ['bbs.nga.cn']
    start_urls = ['https://bbs.nga.cn/thread.php?fid=-7']

    def __init__(self, *args, **kwargs):
        super(NgaSpider, self).__init__(*args, **kwargs)
        # 不再在启动时清空日志文件，让Scrapy的日志轮转机制处理
        # 调度器需要读取日志文件获取统计信息，清空会导致数据丢失

        # 缓存主题的最新回复时间，减少数据库查询
        self.topic_last_reply_cache = {}
        # 初始化缓存管理器
        self.cache_manager = get_cache_manager()
        # 初始化查询优化器
        self.query_optimizer = None  # 将在数据库初始化后设置
        # 初始化数据归档器（月度归档）
        self.data_archiver = None  # 将在数据库初始化后设置
        # 数据库相关属性
        self.db_session = None
        self.db_url = kwargs.get('db_url')  # 允许从命令行传入db_url
        self.process = psutil.Process(os.getpid())  # 初始化监控
    
    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(NgaSpider, cls).from_crawler(crawler, *args, **kwargs)
        # 初始化数据库连接
        spider._init_db()
        return spider
    
    def _init_db(self):
        """初始化数据库连接"""
        from ..utils.db_utils import create_db_session
        from ..utils.data_archiver import DataArchiver
        try:
            # 使用scoped_session包装，确保线程安全
            session_factory = create_db_session(self.db_url)
            if session_factory is None:
                raise RuntimeError("无法创建数据库会话工厂")

            self.db_session = scoped_session(lambda: session_factory)

            # 初始化查询优化器
            self.query_optimizer = QueryOptimizer(self.db_session, self.logger)

            # 初始化数据归档器（月度归档）
            if self.data_archiver is None:
                self.data_archiver = DataArchiver(
                    self.db_session,
                    archive_dir='./archive',
                    config={
                        'enabled': True,
                        'archive_threshold_days': 30,  # 30天未更新则归档
                    }
                )

            self.logger.info("数据库连接和优化组件初始化成功")
        except Exception as e:
            self.logger.error(f"数据库初始化失败: {e}")
            raise
    
    def close(self, reason):
        """爬虫关闭时清理资源"""
        # 执行月度数据归档
        if hasattr(self, 'data_archiver') and self.data_archiver:
            try:
                self.logger.info("开始执行月度数据归档...")
                archive_results = self.data_archiver.auto_archive()
                self.logger.info(f"归档结果: {archive_results}")

                # 清理过期归档文件
                cleaned_count = self.data_archiver.cleanup_old_archives(retention_days=365)
                self.logger.info(f"清理了 {cleaned_count} 个过期归档文件")

            except Exception as e:
                self.logger.error(f"数据归档失败: {e}")

        # 关闭数据库会话
        if hasattr(self, 'db_session') and self.db_session:
            try:
                self.db_session.remove()
                self.logger.info("数据库会话已关闭")
            except Exception as e:
                self.logger.error(f"关闭数据库会话时出错: {e}")
        self.logger.info(f"关闭爬虫方式: {reason}")
        #super().close(reason)
    
    def print_stats(self):
        """打印进度和性能统计信息"""
        cpu = self.process.cpu_percent(interval=1)
        mem = self.process.memory_info().rss / 1024 / 1024
        self.logger.debug(f"📊 CPU: {cpu}% | Memory: {mem:.2f} MB")

        # 获取数据库统计
        if self.db_session:
            try:
                from ..models import Topic, Reply, User
                topic_count = self.db_session.query(Topic).count()
                reply_count = self.db_session.query(Reply).count()
                user_count = self.db_session.query(User).count()
                self.logger.debug(f"📈 DB统计: 主题={topic_count}, 回复={reply_count}, 用户={user_count}")
            except Exception as e:
                self.logger.debug(f"⚠️ 获取数据库统计失败: {e}")

    def parse(self, response):
        # 解析主题列表页
        pageNum = 11
        self.logger.info(f"🚀 开始爬取NGA论坛水区，共需爬取 {pageNum-1} 页主题列表")
        for page in range(1, pageNum):  # 爬取前pageNum页
            self.logger.debug(f"📄 生成第 {page} 页主题列表页请求")
            yield Request(
                url=f"https://bbs.nga.cn/thread.php?fid=-7&page={page}",
                callback=self.parse_topic_list,
                meta={'page': page}
            )

    def parse_topic_list(self, response):
        """两阶段主题列表解析：阶段1-收集所有主题信息"""
        # 解析主题列表
        page = response.meta.get('page', 'unknown')
        self.logger.debug(f"📝 开始解析第 {page} 页主题列表 (URL: {response.url})")

        # 🔍 [DEBUG] 添加详细的页面信息
        content_length = len(response.text)
        self.logger.debug(f"🔍 [DEBUG] 页面内容长度: {content_length} 字符")

        # 保存页面HTML用于调试
        self._save_response_html(response, page, content_length)

        # 检查页面是否包含NGA内容
        if 'nga' not in response.text.lower() and 'bbs.nga.cn' not in response.url:
            self.logger.error(f"❌ [DEBUG] 页面可能不是NGA内容，保存HTML文件用于调试")
            self._save_response_html(response, page, content_length, reason="not_nga_content")

        # 检查是否有反爬虫提示
        anti_bot_keywords = ['访问过于频繁', 'IP被封', '验证码', 'captcha', '人机验证', '您的访问异常']
        if any(keyword in response.text for keyword in anti_bot_keywords):
            self.logger.error(f"❌ [DEBUG] 检测到反爬虫提示: {[kw for kw in anti_bot_keywords if kw in response.text]}")
            self._save_response_html(response, page, content_length, reason="anti_bot_detected")

        # 查找主题行
        rows = response.xpath('//*[contains(@class, "topicrow")]')
        self.logger.debug(f"📊 第 {page} 页主题列表共找到 {len(rows)} 个主题")

        # 阶段1: 收集所有主题信息
        topics_data = self._collect_topics_from_page(rows, page)

        if not topics_data:
            self.logger.warning(f"⚠️ 第 {page} 页没有收集到有效主题")
            self.logger.warning(f"⚠️ [DEBUG] 详细分析:")
            self.logger.warning(f"  - 原始rows数量: {len(rows)}")
            self.logger.warning(f"  - 页面内容长度: {content_length}")
            self.logger.warning(f"  - URL: {response.url}")

            # 🔍 [DEBUG] 尝试分析页面结构
            self._analyze_page_structure(response, rows, page)

            # 保存HTML用于调试
            self.logger.debug(f"💾 [DEBUG] 保存HTML文件用于调试...")
            self._save_response_html(response, page, content_length, reason="no_topics_found")

            return

        # 阶段2: 批量查询数据库信息
        all_tids = list(topics_data.keys())
        self.logger.debug(f"🗄️ [DB调试] 第{page}页: 准备查询{len(all_tids)}个主题的数据库记录")
        db_info = self.batch_query_topics_from_db(all_tids)
        self.logger.debug(f"🗄️ [DB调试] 第{page}页: 数据库返回{len(db_info)}条记录, 新主题数: {len(all_tids) - len(db_info)}")

        # 阶段3: 智能决策哪些主题需要爬取回复
        topics_to_crawl, topics_to_skip = self._decide_topics_to_crawl(topics_data, db_info)
        self.logger.debug(f"🗄️ [DB调试] 第{page}页决策结果: 需爬取{len(topics_to_crawl)}个, 跳过{len(topics_to_skip)}个")

        # 阶段4: 批量生成数据项和请求
        for item in self._process_topics_batch(topics_to_crawl, topics_to_skip, db_info):
            yield item

        self.logger.debug(f"📄 第 {page} 页处理完成: 总计{len(topics_data)}个主题, "
                        f"爬取{len(topics_to_crawl)}个, 跳过{len(topics_to_skip)}个")

    def _save_response_html(self, response, page, content_length, reason=""):
        """保存响应HTML到调试文件"""
        import os
        import time
        from urllib.parse import urlparse

        debug_dir = 'debug_html'
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)

        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        url_hash = hash(response.url) % 10000
        filename = f"{timestamp}_page{page}_{url_hash}_{reason}.html"
        filepath = os.path.join(debug_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                debug_header = f"""
<!-- DEBUG INFO (NGA Spider) -->
<!-- Page: {page} -->
<!-- URL: {response.url} -->
<!-- Content Length: {content_length} -->
<!-- Timestamp: {timestamp} -->
<!-- Reason: {reason} -->
<!-- ======================= -->

"""
                f.write(debug_header)
                f.write(response.text)

            self.logger.debug(f"💾 [DEBUG] HTML已保存: {filepath}")
            return filepath
        except Exception as e:
            self.logger.error(f"❌ [DEBUG] 保存HTML失败: {e}")
            return None

    def _analyze_page_structure(self, response, rows, page):
        """分析页面结构，找出为什么没有找到主题"""
        try:
            # 检查页面标题
            title = response.xpath('//title/text()').get()
            self.logger.warning(f"  - 页面标题: {title}")

            # 检查是否有错误信息
            error_selectors = [
                '//*[contains(text(), "404")]',
                '//*[contains(text(), "页面不存在")]',
                '//*[contains(text(), "访问被拒绝")]',
                '//*[contains(text(), "请登录")]',
            ]
            for selector in error_selectors:
                error_text = response.xpath(selector).get()
                if error_text:
                    self.logger.warning(f"  - 发现错误信息: {error_text[:100]}")

            # 检查所有class包含row的元素
            all_rows = response.xpath('//*[contains(@class, "row")]')
            self.logger.warning(f"  - 包含'row' class的元素数量: {len(all_rows)}")

            # 检查所有table行
            table_rows = response.xpath('//tr')
            self.logger.warning(f"  - 所有tr元素数量: {len(table_rows)}")

            # 检查是否有任何链接
            links = response.xpath('//a/@href').getall()
            nga_links = [link for link in links if 'nga' in link or 'tid=' in link]
            self.logger.warning(f"  - 总链接数: {len(links)}, NGA相关链接数: {len(nga_links)}")

            # 检查页面是否包含预期的HTML结构
            if 'topicrow' in response.text:
                self.logger.warning(f"  - 页面包含'topicrow'字符串，但XPath未找到元素")
            else:
                self.logger.warning(f"  - 页面不包含'topicrow'字符串")

            # 检查是否为空页面或重定向
            if content_length < 500:
                self.logger.warning(f"  - 页面内容过短，可能是空页面或重定向页面")

        except Exception as e:
            self.logger.error(f"  - 分析页面结构时出错: {e}")

    def _collect_topics_from_page(self, rows, page):
        """阶段1: 从页面收集所有主题的基础信息"""
        topics_data = {}
        idx = 0

        for idx, row in enumerate(rows, 1):
            self.logger.debug(f"🔍 收集第 {page} 页第 {idx} 个主题信息")

            # 提取基础信息
            topic_link = row.xpath('.//a[contains(@class, "topic")]/@href').get()
            if not topic_link or 'tid=' not in topic_link:
                continue

            tid = topic_link.split('tid=')[1].split('&')[0]
            title = row.xpath('.//a[contains(@class, "topic")]/text()').get()
            if title == '帖子发布或回复时间超过限制':
                continue

            poster_id = row.xpath('.//*[@class="author"]/@title').re_first(r'用户ID (\d+)')
            poster_name = row.xpath('.//*[@class="author"]/text()').get()
            post_time = row.xpath('.//span[contains(@class, "postdate")]/@title').get()
            re_num = row.xpath('.//*[@class="replies"]/text()').get()

            # 如果主题发布时间为None，使用当前时间
            if not post_time:
                post_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                self.logger.debug(f"🕒 主题 {tid} 无法获取发布时间，使用当前时间: {post_time}")

            # 提取最后回复时间（多种方式）
            last_reply_date = self._extract_last_reply_date(row)

            # 获取分区信息
            partition = '水区'
            partition_el = row.xpath('.//td[@class="c2"]/span[@class="titleadd2"]/a[@class="silver"]/text()')
            if partition_el:
                partition = partition_el.get()

            # 存储主题信息
            topics_data[tid] = {
                'title': title,
                'poster_id': poster_id,
                'poster_name': poster_name,
                'post_time': post_time,
                're_num': re_num,
                'last_reply_date': last_reply_date,
                'partition': partition,
                'row_index': idx,
                'page': page
            }

        self.logger.debug(f"📋 第 {page} 页收集完成，共收集 {len(topics_data)} 个有效主题")
        return topics_data

    def _extract_last_reply_date(self, row):
        """提取最后回复时间的多种方式"""
        last_reply_date = None

        # 方式1: 从 .replydate 的 title 属性提取
        last_reply_date = row.xpath('.//a[contains(@class, "replydate")]/@title').get()

        # 方式2: 从 .replydate 的文本内容提取（相对时间）
        if not last_reply_date:
            alt_date = row.xpath('.//a[contains(@class, "replydate")]/text()').get()
            if alt_date and alt_date not in ['刚才', '今天', '昨天', '前天']:
                last_reply_date = alt_date

        # 方式3: 查找所有有title属性的元素，筛选出时间格式的
        if not last_reply_date:
            time_candidates = row.xpath('.//*[@title and string-length(@title) > 8]/@title').getall()
            for candidate in time_candidates:
                if self._is_nga_time_format(candidate):
                    last_reply_date = candidate
                    break

        # 方式4: 使用正则从整行文本中提取时间
        if not last_reply_date:
            row_text = row.xpath('string(.)').get()
            last_reply_date = self._extract_time_from_text(row_text)

        # 如果网页时间为None，使用当前时间作为fallback
        if not last_reply_date:
            last_reply_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        return last_reply_date

    def _decide_topics_to_crawl(self, topics_data, db_info):
        """阶段3: 智能决策哪些主题需要爬取回复"""
        topics_to_crawl = []
        topics_to_skip = []

        for tid, topic_info in topics_data.items():
            web_last_reply = topic_info['last_reply_date']
            db_topic_info = db_info.get(tid, {})
            db_last_reply = db_topic_info.get('last_reply_date')

            # 更新缓存
            self.topic_last_reply_cache[tid] = db_last_reply

            # 决策逻辑：是否需要爬取该主题的回复
            should_crawl = self._should_crawl_topic_replies(tid, web_last_reply, db_last_reply, topic_info, db_topic_info)

            if should_crawl:
                topics_to_crawl.append((tid, topic_info, db_last_reply))
                self.logger.debug(f"✅ 主题 {tid} 需要爬取回复 (网页:{web_last_reply}, 数据库:{db_last_reply})")
            else:
                topics_to_skip.append((tid, topic_info, db_last_reply))
                self.logger.debug(f"⏭️  主题 {tid} 跳过回复爬取 (网页:{web_last_reply}, 数据库:{db_last_reply})")

        return topics_to_crawl, topics_to_skip

    def _should_crawl_topic_replies(self, tid, web_last_reply, db_last_reply, topic_info, db_topic_info=None):
        """判断是否需要爬取主题的回复"""
        # 如果数据库中没有记录，需要爬取
        if not db_last_reply:
            return True

        # 如果网页时间比数据库时间新，需要爬取
        if web_last_reply and self.is_newer(web_last_reply, db_last_reply):
            return True

        # 如果回复数量有变化，可能需要爬取（可选的启发式判断）
        web_re_num = topic_info.get('re_num', '0') or '0'
        db_re_num = str(db_topic_info.get('re_num', 0)) if db_topic_info and db_topic_info.get('re_num') else '0'
        if web_re_num and db_re_num and web_re_num != db_re_num:
            self.logger.debug(f"🔢 主题 {tid} 回复数变化: 网页{web_re_num} vs 数据库{db_re_num}")
            return True

        return False

    def _process_topics_batch(self, topics_to_crawl, topics_to_skip, db_info):
        """阶段4: 批量处理所有主题，生成数据项和请求"""
        reply_requests_count = 0
        total_count = len(topics_to_crawl)

        # 处理需要爬取的主题
        # 关键修复：添加小延迟控制生成速度，避免队列拥塞
        # 生成速度必须 <= 处理速度，否则会堆积
        for i, (tid, topic_info, db_last_reply) in enumerate(topics_to_crawl):
            # 每生成8个请求暂停0.5秒（与并发数匹配），让Scrapy有时间处理
            if i > 0 and i % 8 == 0:
                self.logger.debug(f"⏱️ [节流] 已生成{i}/{total_count}个请求，暂停0.5秒让调度器处理...")
                time.sleep(0.5)
            # 生成TopicItem
            topic_item = TopicItem(
                tid=tid,
                title=topic_info['title'],
                poster_id=topic_info['poster_id'],
                post_time=topic_info['post_time'],
                re_num=topic_info['re_num'],
                sampling_time=self._now_time(),
                last_reply_date=topic_info['last_reply_date'],
                partition=topic_info['partition']
            )
            yield topic_item

            # 生成UserItem
            if topic_info['poster_id']:
                user_item = UserItem(
                    uid=topic_info['poster_id'],
                    name=topic_info['poster_name'] or '',
                    user_group='',
                    reg_date='',
                    prestige='',
                    history_re_num=''
                )
                yield user_item

            # 生成回复页请求（并发由 Scrapy 的 CONCURRENT_REQUESTS 控制）
            reply_request = Request(
                url=f"https://bbs.nga.cn/read.php?tid={tid}&page=999",
                callback=self.parse_replies,
                meta={'tid': tid, 'db_last_reply': db_last_reply},
                priority=100,
                dont_filter=False
            )
            self.logger.debug(f"🔄 正在yield请求 {tid}...")
            yield reply_request
            reply_requests_count += 1
            self.logger.debug(f"✅ 成功yield请求 {tid}，计数: {reply_requests_count}/{total_count}")
            self.logger.debug(f"🚀 主题 {tid}: 已生成回复页请求 (第{i+1}/{total_count}个)")
            
            # 【诊断日志】每生成10个请求检查一次队列状态
            if (i + 1) % 10 == 0:
                if hasattr(self.crawler.engine, 'scheduler') and hasattr(self.crawler.engine.scheduler, 'queue'):
                    queue_size = len(self.crawler.engine.scheduler.queue)
                    self.logger.debug(f"📊 [生成请求队列诊断] 已生成{i+1}个请求，当前调度队列长度: {queue_size}")

        self.logger.debug(f"🗄️ [DB调试] 批处理完成: 生成{reply_requests_count}个回复页请求, 跳过{len(topics_to_skip)}个主题")

        # 队列状态监控 - 关键调试信息
        if hasattr(self.crawler.engine, 'scheduler') and hasattr(self.crawler.engine.scheduler, 'queue'):
            queue_size = len(self.crawler.engine.scheduler.queue)
            self.logger.debug(f"📊 [队列监控] 当前调度队列长度: {queue_size}, 生成请求总数: {reply_requests_count}")
            if queue_size > 100:
                self.logger.warning(f"⚠️ [队列拥塞] 队列长度({queue_size})超过100，可能导致处理延迟！")
        else:
            self.logger.warning("⚠️ 无法获取调度器队列状态")

        # 处理跳过的主题（只生成TopicItem，不生成请求）
        for tid, topic_info, db_last_reply in topics_to_skip:
            # 即使跳过回复爬取，也要更新主题信息（保持数据新鲜度）
            topic_item = TopicItem(
                tid=tid,
                title=topic_info['title'],
                poster_id=topic_info['poster_id'],
                post_time=topic_info['post_time'],
                re_num=topic_info['re_num'],
                sampling_time=self._now_time(),
                last_reply_date=topic_info['last_reply_date'],
                partition=topic_info['partition']
            )
            yield topic_item

            self.logger.debug(f"📝 主题 {tid}: 已更新主题信息（跳过回复爬取）")

    def get_last_reply_from_db(self, tid):
        """从数据库获取主题的最后回复时间"""
        if not hasattr(self, 'db_session') or not self.db_session:
            self.logger.error("数据库会话未初始化")
            return None

        try:
            from ..models import Topic  # 局部导入避免循环引用
            topic = self.db_session.query(Topic).filter_by(tid=tid).first()
            return topic.last_reply_date if topic else None
        except SQLAlchemyError as e:
            self.logger.error(f"查询数据库出错: {e}")
            return None
        except Exception as e:
            self.logger.error(f"获取最后回复时间时发生意外错误: {e}")
            return None

    def batch_query_topics_from_db(self, tids, batch_size=100, use_cache=True, use_exists_optimization=True):
        """批量查询数据库中多个主题的信息（终极优化版本）

        Args:
            tids: 主题ID列表
            batch_size: 每批查询的主题数量，默认100
            use_cache: 是否使用缓存，默认True
            use_exists_optimization: 是否使用EXISTS优化，默认True

        Returns:
            dict: {tid: {'last_reply_date': str, 'post_time': str, 're_num': int}}
        """
        if not hasattr(self, 'db_session') or not self.db_session:
            self.logger.error("数据库会话未初始化")
            return {}

        if not tids:
            return {}

        # 导入模块
        from ..models import Topic
        import time

        total_tids = len(tids)
        result = {}
        cached_count = 0
        db_query_count = 0
        query_strategy = 'in_query'  # 默认查询策略

        # 缓存键前缀
        cache_prefix = 'topic_info:'

        # 第一步：优先从缓存获取数据
        if use_cache:
            for tid in tids:
                cache_key = f"{cache_prefix}{tid}"
                cached_data = self.cache_manager.get(cache_key)
                if cached_data is not None:
                    result[tid] = cached_data
                    cached_count += 1

            self.logger.debug(f"💾 [缓存] 从缓存获取 {cached_count}/{total_tids} 个主题数据")

        # 第二步：查询数据库获取未缓存的数据
        if use_cache:
            # 找出未缓存的TID
            uncached_tids = [tid for tid in tids if tid not in result]
        else:
            uncached_tids = tids

        if uncached_tids:
            # 根据数据量选择最优查询策略
            if use_exists_optimization and len(uncached_tids) > 1000 and self.query_optimizer:
                # 大量数据：使用EXISTS查询优化
                query_strategy = 'exists_query'
                existing_tids = self.query_optimizer.check_topics_exist_exists(uncached_tids)

                # 只查询存在的主题
                if existing_tids:
                    existing_list = list(existing_tids)
                    for i in range(0, len(existing_list), batch_size):
                        batch_tids = existing_list[i:i + batch_size]
                        batch_num = i // batch_size + 1

                        query_start_time = time.time()
                        try:
                            topics = self.db_session.query(Topic).filter(Topic.tid.in_(batch_tids)).all()

                            batch_result_count = 0
                            for topic in topics:
                                topic_data = {
                                    'last_reply_date': topic.last_reply_date,
                                    'post_time': topic.post_time,
                                    're_num': topic.re_num
                                }
                                result[topic.tid] = topic_data
                                batch_result_count += 1

                                # 写入缓存
                                if use_cache:
                                    cache_key = f"{cache_prefix}{topic.tid}"
                                    self.cache_manager.set(cache_key, topic_data)

                            db_query_count += 1

                            batch_elapsed = time.time() - query_start_time
                            self.logger.debug(
                                f"✅ [EXISTS优化] 批次 {batch_num}: 耗时{batch_elapsed:.3f}s, "
                                f"返回{batch_result_count}条记录"
                            )

                        except Exception as e:
                            self.logger.error(f"EXISTS优化批次 {batch_num} 查询出错: {e}")
                            continue

            else:
                # 中小数据：使用标准分批IN查询
                query_strategy = 'batch_in_query'
                total_batches = (len(uncached_tids) + batch_size - 1) // batch_size
                query_count = 0
                start_time = time.time()

                for i in range(0, len(uncached_tids), batch_size):
                    batch_tids = uncached_tids[i:i + batch_size]
                    batch_num = i // batch_size + 1

                    query_count += 1
                    query_start_time = time.time()

                    try:
                        # 记录查询日志
                        if total_batches > 1:
                            self.logger.debug(f"🗄️ [DB调试] 批次 {batch_num}/{total_batches}: 查询{len(batch_tids)}个主题")
                        else:
                            self.logger.debug(f"🗄️ [DB调试] 查询{len(batch_tids)}个主题")

                        # 执行批次查询
                        topics = self.db_session.query(Topic).filter(Topic.tid.in_(batch_tids)).all()

                        # 处理查询结果
                        batch_result_count = 0
                        for topic in topics:
                            topic_data = {
                                'last_reply_date': topic.last_reply_date,
                                'post_time': topic.post_time,
                                're_num': topic.re_num
                            }
                            result[topic.tid] = topic_data
                            batch_result_count += 1

                            # 写入缓存
                            if use_cache:
                                cache_key = f"{cache_prefix}{topic.tid}"
                                self.cache_manager.set(cache_key, topic_data)

                        db_query_count += 1

                        # 记录单批查询耗时
                        batch_elapsed = time.time() - query_start_time

                        # 慢查询告警（>500ms）
                        if batch_elapsed > 0.5:
                            self.logger.warning(
                                f"⚠️ [慢查询告警] 批次 {batch_num} 查询耗时 {batch_elapsed:.3f}s "
                                f"(查询{len(batch_tids)}个主题，返回{batch_result_count}条记录)"
                            )

                        if total_batches > 1:
                            self.logger.debug(
                                f"✅ 批次 {batch_num} 完成: 耗时{batch_elapsed:.3f}s, "
                                f"返回{batch_result_count}条记录"
                            )

                    except SQLAlchemyError as e:
                        self.logger.error(f"批次 {batch_num} 批量查询数据库出错: {e}")
                        continue
                    except Exception as e:
                        self.logger.error(f"批次 {batch_num} 批量查询时发生意外错误: {e}")
                        continue

                # 记录总查询耗时
                total_elapsed = time.time() - start_time

                # 记录到监控系统
                monitor = get_monitor()
                monitor.record_query(total_elapsed, 'batch', batch_size, len(uncached_tids))

                # 查询性能统计
                avg_query_time = total_elapsed / query_count if query_count > 0 else 0

                self.logger.debug(
                    f"🗄️ [DB性能统计] 未缓存查询: {len(uncached_tids)}个主题, "
                    f"分{query_count}批, 总耗时{total_elapsed:.3f}s, "
                    f"平均每批{avg_query_time:.3f}s"
                )

                # 整体慢查询告警（>2000ms）
                if total_elapsed > 2.0:
                    self.logger.warning(
                        f"⚠️ [整体慢查询告警] 批量查询总耗时 {total_elapsed:.3f}s "
                        f"(查询{len(uncached_tids)}个主题，建议优化)"
                    )

                # 每1000个主题的性能报告
                if len(uncached_tids) >= 1000:
                    throughput = len(uncached_tids) / total_elapsed if total_elapsed > 0 else 0
                    self.logger.debug(
                        f"📊 [性能报告] 查询吞吐量: {throughput:.1f} 主题/秒 "
                        f"({len(uncached_tids)}个主题 / {total_elapsed:.3f}s)"
                    )

        # 第三步：汇总统计信息
        cache_hit_rate = (cached_count / total_tids * 100) if total_tids > 0 else 0

        self.logger.debug(
            f"🎯 [查询策略] 使用策略: {query_strategy}, "
            f"缓存命中: {cached_count}/{total_tids} ({cache_hit_rate:.1f}%), "
            f"数据库查询: {db_query_count}批次, "
            f"找到{len(result)}条记录"
        )

        # 缓存命中率低告警（<50%）
        if use_cache and cache_hit_rate < 50:
            self.logger.warning(
                f"⚠️ [缓存命中率告警] 缓存命中率 {cache_hit_rate:.1f}% 较低 "
                f"(建议检查缓存配置或增加缓存时间)"
            )

        return result

    # 其他方法保持不变...
    def parse_replies(self, response):
        # 立即记录方法被调用，用于调试
        self.logger.debug(f"🎯 parse_replies方法被调用! URL: {response.url}, Status: {response.status}")

        # 【诊断日志】记录调度队列状态
        if hasattr(self.crawler.engine, 'scheduler') and hasattr(self.crawler.engine.scheduler, 'queue'):
            queue_size = len(self.crawler.engine.scheduler.queue)
            self.logger.debug(f"📊 [parse_replies队列诊断] 当前调度队列长度: {queue_size}")

        tid = response.meta['tid']
        db_last_reply = response.meta.get('db_last_reply')
        current_page = response.meta.get('current_page', 'unknown')
        last_page = response.meta.get('last_page', 'unknown')

        self.logger.debug(f"💬 开始解析主题 {tid} 的回复 (当前页: {current_page}/{last_page}, URL: {response.url})")

        meta={'tid': tid}

        if 'last_page' not in response.meta:
            # ① 原始响应体里的 __PAGE 脚本含总页数
            #    （var __PAGE = {0:'基础URL',1:总页数,2:当前页,3:每页条数}）——
            #    服务器原始体无 DOM 版翻页控件（最后页/invert，JS 生成），此为页数权威来源（2026-10-13）
            m_page = re.search(r"var __PAGE\s*=\s*\{0:'[^']*',1:(\d+),2:\d+,3:\d+\}", response.text)
            if m_page:
                last_page = int(m_page.group(1))
            else:
                last_page_link = response.xpath('//a[contains(@class, "invert") and @title="最后页"]/@href').get()
                if last_page_link:
                    last_page = int(parse_qs(last_page_link.split('?')[1]).get('page', [1])[0])
                    #self.logger.info(f"最后一页{last_page}获取")
                else:
                    page_links = [int(p.split('=')[-1]) for p in response.xpath('//a[contains(@href, "page=")]/@href').re(r'page=\d+')]
                    last_page = max(page_links) if page_links else 1

            meta['last_page'] = last_page
            meta['current_page'] = last_page

        if 'current_page' in response.meta:
            meta['current_page'] = response.meta['current_page']

        new_page_flag=True

        replies = response.xpath('//*[@class="forumbox postbox"]')
        self.logger.debug(f"📜 主题 {tid}: 当前页 {current_page}/{last_page} 共有 {len(replies)} 条回复")

        for idx, reply in enumerate(replies, 1):
            self.logger.debug(f"📝 主题 {tid}: 开始处理第 {idx} 条回复 (当前页 {current_page}/{last_page})")
            post_id = reply.xpath('.//*[starts-with(@id, "postcontainer")]/a[1]/@id').get()

            # 安全检查：如果无法获取 post_id，跳过该回复
            if not post_id:
                self.logger.warning(f"无法获取 post_id，跳过该回复 (tid={tid})")
                continue

            # 统一使用纯数字格式
            if post_id == 'pid0Anchor':
                # 主楼使用 tid 作为 rid，纯数字格式
                post_id = tid
            elif 'pid' in post_id and 'Anchor' in post_id:
                # 普通回复：从 Anchor 格式提取纯数字
                # 例如：pid849526462Anchor → 849526462
                post_id = post_id.replace('pid', '').replace('Anchor', '')
            elif post_id.isdigit():
                # 已经是纯数字格式，直接使用
                pass
            else:
                # 其他未知格式，记录警告并跳过
                self.logger.warning(f"未知的 post_id 格式: {post_id} (tid={tid})")
                continue
                
            poster_href = reply.xpath('.//*[starts-with(@id, "postauthor")]/@href').get()
            poster_id = poster_href.split('uid=')[1].split('&')[0] if poster_href and 'uid=' in poster_href else ''
            poster_name = reply.xpath('.//*[starts-with(@id, "postauthor")]/text()').get()
            
            content = self._extract_post_content(reply)

            recommendvalue = reply.xpath('.//span[contains(@class,"recommendvalue")]/text()').get('0')
            post_time = reply.xpath('.//*[starts-with(@id, "postdate")]/text()').get()

            # 如果回复时间为None，使用当前时间
            if not post_time:
                post_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                self.logger.debug(f"🕒 回复 {post_id} 无法获取时间，使用当前时间: {post_time}")

            # 如果设置了数据库最后回复时间，且当前回复时间不新于数据库记录，则跳过
            if db_last_reply and not self.is_newer(post_time, db_last_reply):
                self.logger.debug(f"跳过回复 {post_id}，回复时间 {post_time} 不新于数据库记录 {db_last_reply}")
                new_page_flag=False
                continue
            
            parent_rid = self._extract_parent_rid(reply, content)

            # 图片 URL：正文 BBCode [img]（快照前态）＋ <img> 元素（快照落在 JS 渲染后）
            image_urls = self._extract_image_urls(reply, content)

            reply_item = ReplyItem(
                rid=post_id,
                tid=tid,
                parent_rid=parent_rid,
                content=content,
                recommendvalue=recommendvalue,
                post_time=post_time,
                poster_id=poster_id,
                sampling_time=self._now_time(),
                image_urls=image_urls  # 添加图片URL列表
            )
            self.logger.debug(f"✅ 主题 {tid}: 成功提取回复 {post_id} (时间: {post_time}, 用户: {poster_id}, 推荐值: {recommendvalue})")
            yield reply_item

            # 创建用户信息（只包含基本信息，不发起额外请求）
            if poster_id:
                self.logger.debug(f"👤 主题 {tid}: 为用户 {poster_id} 生成UserItem")
                user_item = UserItem(
                    uid=poster_id,
                    name=poster_name or '',
                    user_group='',
                    reg_date='',
                    prestige='',
                    history_re_num=''
                )
                yield user_item

        self.logger.debug(f"📄 主题 {tid}: 页面 {current_page}/{last_page} 解析完成，准备处理上一页")
        # 处理上一页
        if new_page_flag and meta['current_page'] > 1:
            meta['current_page'] = meta['current_page'] - 1
            self.logger.debug(f"⬅️ 主题 {tid}: 翻到上一页 {meta['current_page']} 页")
            yield Request(
                url=f"https://bbs.nga.cn/read.php?tid={tid}&page={meta['current_page']}",
                callback=self.parse_replies,
                meta=meta
            )
        else:
            self.logger.debug(f"✅ 主题 {tid}: 所有回复页处理完成")

    # ── 正文 / 引用 / 图片提取（2026-10-13 修复「只取首文本节点」截断缺陷）─────
    # 缺陷（坐实于全库扫描＋实页对照）：原实现
    #   content = reply.xpath('…postcontent…/text()').get()
    # 只取 postcontent 元素的**第一个**文本节点（＝正文第一行）。NGA 页面的行边界
    # 是真实 <br> 元素（每行独立文本节点），引用归因头恒独占首行 → 其后（被引正文＋
    # 自有正文）整体丢失。全库受影响下界 ≈128 万条（27.6%）。
    # 实页对照（2026-10-13，tid=47702375）：首节点 82 字 vs 全文 274 字。
    _POSTCONTENT_XPATH = ('.//*[starts-with(@id, "postcontent") '
                          'and string-length(translate(substring(@id, 12), "0123456789", "")) = 0]')
    _PID_RE = re.compile(r'\[pid=(\d+),')
    _IMG_BBCODE_RE = re.compile(r'\[img\](.*?)\[/img\]', re.S)
    _NGA_ATTACH_BASE = 'https://img.nga.178.com/attachments/'

    def _extract_post_content(self, reply):
        """提取楼层正文：postcontent 元素下**全部**文本节点，真实 <br> 元素还原为换行。

        按文档顺序遍历 `.//text() | .//br`（XPath 并集保证文档序）；文本节点与元素
        节点的判据用 `isinstance(node.root, str)`——parsel 的 `.type` 会被父级继承
        （并集节点的 type 恒为 'html'，不可用，2026-10-13 冒烟坐实的坑）。
        转义文本里的字面 `<br/>`（引文内嵌 HTML 源）原样保留，不在本层再解释。
        """
        els = reply.xpath(self._POSTCONTENT_XPATH)
        if not els:
            return None
        parts = []
        for node in els[0].xpath('.//text() | .//br'):
            root = node.root
            parts.append(str(root) if isinstance(root, str) else '\n')
        return ''.join(parts)

    def _extract_parent_rid(self, reply, content):
        """从引用标记解析被回复楼的 rid。

        快照时刻（domcontentloaded）引用多为 BBCode 文本形态
        （`[b]Reply to [pid=…]` / `[quote][pid=…]`），元素形态（div.quote）几乎不存——
        旧实现只走路元素，主表 137 万条仅 26 条非空。现优先从正文解析首个 `[pid=…]`；
        元素路径保留为后备（快照落在 JS 渲染后、引用为 `+R by` 结构时）。
        """
        if content:
            m = self._PID_RE.search(content)
            if m:
                return m.group(1)
        quote_link = reply.xpath('.//a[contains(@title, "打开链接")]/@href').get()
        if not quote_link:
            quote_link = reply.xpath('.//div[contains(@class, "quote")]//a/@href').get()
        if quote_link and 'pid=' in quote_link:
            return quote_link.split('pid=')[1].split('&')[0]
        return None

    def _extract_image_urls(self, reply, content):
        """提取图片 URL（去重保序）。

        ① 正文 BBCode `[img]…[/img]`——快照前态的主要形态；相对路径（`./mon_…`）
           补全为附件 CDN 绝对地址（`img.nga.178.com/attachments/`）。
        ② `<img>` 元素 src——快照落在 JS 渲染后时的形态（表情 `smile/`、附件
           `attachments/`）；过滤 copyChk 占位图（`about:blank`）。
        """
        urls = []
        if content:
            for raw in self._IMG_BBCODE_RE.findall(content):
                u = raw.strip()
                if u.startswith('./'):
                    u = self._NGA_ATTACH_BASE + u[2:]
                elif u.startswith('mon_') or u.startswith('-'):
                    u = self._NGA_ATTACH_BASE + u
                if u.startswith('http'):
                    urls.append(u)
        for img in reply.xpath('.//img'):
            src = img.xpath('@src').get()
            if src and src != 'about:blank' and ('attachments' in src or 'smile' in src):
                urls.append(src)
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    # 其他方法保持不变...
    def parse_user(self, response):
        uid = response.meta['uid']
        user_group = response.xpath('//label[contains(text(), "用 户 组")]/../span/span/text()').get('匿名用户')
        reg_date = response.xpath('//label[contains(text(), "注册日期")]/../span/text()').get()
        
        user_item=UserItem(
            uid=uid,
            user_group=user_group,
            reg_date=reg_date,
            prestige='',
            history_re_num='')
        yield user_item

    def is_newer(self, time1, time2):
        """比较两个时间字符串，判断time1是否比time2新"""
        try:
            # 处理NGA的时间格式可能不一致的情况
            dt1 = self._parse_nga_time(time1)
            dt2 = self._parse_nga_time(time2)
            self.logger.debug(f"时间比较:  time1: {dt1}, time2: {dt2}，结果：{dt1 >= dt2}")
            return dt1 >= dt2
        except Exception as e:
            self.logger.error(f"时间比较错误: {e}, web_time: {time1}, db_time: {time2}")
            return True  # 如果解析失败，默认处理为新回复

    def _parse_nga_time(self, time_str):
        """解析NGA的各种时间格式"""
        if not time_str:
            return datetime.min
        
        # 尝试常见格式（按优先级排序）
        formats = [
            '%Y-%m-%d %H:%M:%S',  # 标准格式 2025-04-19 17:00:00
            '%y-%m-%d %H:%M:%S',  # 简写年份 25-04-19 17:00:00
            '%d-%m-%y %H:%M:%S',  # 日-月-年 19-04-25 17:00:00
            '%Y-%m-%d %H:%M',     # 缺少秒
            '%y-%m-%d %H:%M',     # 简写年份缺少秒
            '%d-%m-%y %H:%M',     # 日-月-年缺少秒
            '%m-%d %H:%M',        # 缺少年和秒
            '%H:%M:%S',           # 只有时间
            '%H:%M'               # 只有小时和分钟
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        
        # 如果都不匹配，返回最小时间
        self.logger.warning(f"无法解析的时间格式: {time_str}")
        return datetime.min


    def _is_nga_time_format(self, time_str):
        """检查字符串是否为NGA时间格式"""
        if not time_str:
            return False
        import re
        # 匹配 NGA 时间格式: 25-11-30 15:59, 2025-11-30 15:59:30 等
        patterns = [
            r'\d{2,4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?',  # 标准格式
            r'\d{2,4}-\d{2}-\d{2}\s+\d{2}:\d{2}',             # 简化格式
        ]
        for pattern in patterns:
            if re.match(pattern, time_str.strip()):
                return True
        return False

    def _extract_time_from_text(self, text):
        """从文本中使用正则表达式提取时间"""
        if not text:
            return None
        import re
        # 多种时间格式的正则表达式
        patterns = [
            r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',  # 2025-11-30 15:59:30
            r'(\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',  # 25-11-30 15:59:30
            r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})',        # 2025-11-30 15:59
            r'(\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2})',        # 25-11-30 15:59
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _now_time(self):
        return time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
