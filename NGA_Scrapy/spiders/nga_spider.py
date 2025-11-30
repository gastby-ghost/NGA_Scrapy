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

import scrapy
from scrapy import Request
from ..items import TopicItem, ReplyItem, UserItem
from urllib.parse import parse_qs, urljoin
import time
from datetime import datetime
from sqlalchemy.orm import scoped_session
from sqlalchemy.exc import SQLAlchemyError
from ..models import Base  # 确保导入Base
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
        try:
            # 使用scoped_session包装，确保线程安全
            session_factory = create_db_session(self.db_url)
            if session_factory is None:
                raise RuntimeError("无法创建数据库会话工厂")
            
            self.db_session = scoped_session(lambda: session_factory)
            self.logger.info("数据库连接初始化成功")
        except Exception as e:
            self.logger.error(f"数据库初始化失败: {e}")
            raise
    
    def close(self, reason):
        """爬虫关闭时清理资源"""
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
        # 解析主题列表
        page = response.meta.get('page', 'unknown')
        self.logger.debug(f"📝 开始解析第 {page} 页主题列表 (URL: {response.url})")

        rows = response.xpath('//*[contains(@class, "topicrow")]')
        self.logger.debug(f"📊 第 {page} 页主题列表共找到 {len(rows)} 个主题")

        for idx, row in enumerate(rows, 1):
            self.logger.debug(f"🔍 开始处理第 {page} 页第 {idx} 个主题")
            topic_link = row.xpath('.//a[contains(@class, "topic")]/@href').get()
            if not topic_link or 'tid=' not in topic_link:
                continue
                
            tid = topic_link.split('tid=')[1].split('&')[0]
            title = row.xpath('.//a[contains(@class, "topic")]/text()').get()
            if title == '帖子发布或回复时间超过限制':
                continue
                
            poster_id = row.xpath('.//*[@class="author"]/@title').re_first(r'用户ID (\d+)')
            post_time = row.xpath('.//span[contains(@class, "postdate")]/@title').get()
            re_num = row.xpath('.//*[@class="replies"]/text()').get()

            # 【增强】多种方式提取最后回复时间
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

            # 获取数据库中该主题的最后回复时间
            self.logger.debug(f"🔍 主题 {tid}: 查询数据库获取最后回复时间")
            db_last_reply = self.get_last_reply_from_db(tid)
            self.topic_last_reply_cache[tid] = db_last_reply  # 存入缓存
            self.logger.debug(f"📅 主题 {tid}: 数据库记录时间 = {db_last_reply}, 网页时间 = {last_reply_date}")

            # 只有当网页时间比数据库时间新时才处理
            # 注意：如果网页时间为None（解析失败），默认当作新主题处理
            if db_last_reply and last_reply_date and not self.is_newer(last_reply_date, db_last_reply):
                # 网页时间和数据库时间都存在，但网页不新于数据库
                self.logger.info(f"主题 {tid} 没有新回复 (数据库:{db_last_reply} >= 网页:{last_reply_date})")
                continue

            # 如果网页时间为None（新主题或无回复主题）或时间比数据库新，继续处理
            if not last_reply_date:
                if db_last_reply:
                    # 主题没有网页时间，但数据库中有记录（可能是被限制或特殊主题）
                    self.logger.debug(f"⚠️  主题 {tid} 无法获取网页时间，数据库已有记录 (数据库:{db_last_reply})")
                else:
                    # 新主题，没有最后回复时间
                    self.logger.debug(f"✅ 主题 {tid} 没有最后回复时间，当作新主题处理")
            elif db_last_reply:
                # 既有网页时间也有数据库时间
                self.logger.debug(f"✅ 主题 {tid} 网页时间比数据库时间新 (网页:{last_reply_date} > 数据库:{db_last_reply})")
                
            partition = '水区'
            partition_el = row.xpath('.//td[@class="c2"]/span[@class="titleadd2"]/a[@class="silver"]/text()')
            if partition_el:
                partition = partition_el.get()
                
            topic_item = TopicItem(
                tid=tid,
                title=title,
                poster_id=poster_id,
                post_time=post_time,
                re_num=re_num,
                sampling_time=self._now_time(),
                last_reply_date=last_reply_date,
                partition=partition
            )
            yield topic_item
            #self.print_stats() 
            #self.logger.info(f"准备获取主题 {tid} 所有对应用户")
            # 请求用户信息 
            if poster_id:
                user_item=UserItem(
                        uid=poster_id,
                        user_group='',
                        reg_date='',
                        prestige='',
                        history_re_num='')
                yield user_item
            '''
            yield Request(
                url=f"https://bbs.nga.cn/nuke.php?func=ucp&uid={poster_id}",
                callback=self.parse_user,
                meta={'uid': poster_id},
                dont_filter=False
            )'''
            #self.print_stats() 
            # 请求回复页
            yield Request(
                url=f"https://bbs.nga.cn/read.php?tid={tid}&page=999",
                callback=self.parse_replies,
                meta={'tid': tid, 'db_last_reply': db_last_reply}
            )
            #self.print_stats()
            self.logger.debug(f"✅ 主题 {tid}: 已生成所有请求")

        # 主题列表页处理完成
        self.logger.debug(f"📄 第 {page} 页主题列表解析完成，共处理 {idx} 个主题")

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

    # 其他方法保持不变...
    def parse_replies(self, response):
        tid = response.meta['tid']
        db_last_reply = response.meta.get('db_last_reply')
        current_page = response.meta.get('current_page', 'unknown')
        last_page = response.meta.get('last_page', 'unknown')

        self.logger.debug(f"💬 开始解析主题 {tid} 的回复 (当前页: {current_page}/{last_page}, URL: {response.url})")

        meta={'tid': tid}

        if 'last_page' not in response.meta:
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
            
            content = reply.xpath('.//*[starts-with(@id, "postcontent") '
                                 'and string-length(translate(substring(@id, 12), "0123456789", "")) = 0]/text()').get()
            
            recommendvalue = reply.xpath('.//span[contains(@class,"recommendvalue")]/text()').get('0')
            post_time = reply.xpath('.//*[starts-with(@id, "postdate")]/text()').get()
            
            # 如果设置了数据库最后回复时间，且当前回复时间不新于数据库记录，则跳过
            if db_last_reply and not self.is_newer(post_time, db_last_reply):
                self.logger.debug(f"跳过回复 {post_id}，回复时间 {post_time} 不新于数据库记录 {db_last_reply}")
                new_page_flag=False
                continue
            
            parent_rid = None
            if reply.xpath('.//div[contains(@class, "quote")]'):
                quote_link = reply.xpath('.//a[contains(@title, "打开链接")]/@href').get()
                if quote_link and 'pid=' in quote_link:
                    parent_rid = quote_link.split('pid=')[1].split('&')[0]
            
            # 新增图片URL提取逻辑
            image_urls = []
            # 提取所有img标签的src属性（包含data-srcorg备用）
            for img in reply.xpath('.//img'):
                src = img.xpath('@src').get()
                if src and ('attachments' in src or 'smile' in src):
                    image_urls.append(src)

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

            # 请求用户信息
            if poster_id:
                self.logger.debug(f"👤 主题 {tid}: 为用户 {poster_id} 生成UserItem")
                user_item=UserItem(
                    uid=poster_id,
                    user_group='',
                    reg_date='',
                    prestige='',
                    history_re_num='')
                yield user_item
                '''
                yield Request(
                    url=f"https://bbs.nga.cn/nuke.php?func=ucp&uid={poster_id}",
                    callback=self.parse_user,
                    meta={'uid': poster_id},
                    dont_filter=False
                )'''

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
