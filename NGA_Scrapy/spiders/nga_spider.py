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
        cpu = self.process.cpu_percent(interval=1)
        mem = self.process.memory_info().rss / 1024 / 1024
        self.logger.debug(f"CPU: {cpu}% | Memory: {mem:.2f} MB")

    def parse(self, response):
        # 解析主题列表页
        pageNum=11
        for page in range(1, pageNum):  # 爬取前pageNum页
            yield Request(
                url=f"https://bbs.nga.cn/thread.php?fid=-7&page={page}",
                callback=self.parse_topic_list
            )

    def parse_topic_list(self, response):
        # 解析主题列表
        rows = response.xpath('//*[contains(@class, "topicrow")]')
        for row in rows:
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
            last_reply_date = row.xpath('.//a[contains(@class, "replydate")]/@title').get()
            
            # 获取数据库中该主题的最后回复时间
            db_last_reply = self.get_last_reply_from_db(tid)
            self.topic_last_reply_cache[tid] = db_last_reply  # 存入缓存
            
            # 只有当网页时间比数据库时间新时才处理
            if db_last_reply and not self.is_newer(last_reply_date, db_last_reply):
                self.logger.info(f"主题 {tid} 没有新回复 (数据库:{db_last_reply} >= 网页:{last_reply_date})")
                continue
                
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
            #self.logger.info(f"已获取主题 {tid} 所有对应数据")

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
        
        for reply in replies:
            post_id = reply.xpath('.//*[starts-with(@id, "postcontainer")]/a[1]/@id').get()
            if post_id == 'pid0Anchor':
                post_id = tid + post_id
                
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
            yield reply_item
            
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
        
        # 处理上一页
        if new_page_flag and meta['current_page'] > 1:
            meta['current_page'] = meta['current_page'] - 1
            yield Request(
                url=f"https://bbs.nga.cn/read.php?tid={tid}&page={meta['current_page']}",
                callback=self.parse_replies,
                meta=meta
            )

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


    def _now_time(self):
        return time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
