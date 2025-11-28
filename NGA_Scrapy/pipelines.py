# pipelines.py
# 以下是该NGA Pipeline代码的功能和特性总结，基于这些信息可以完整还原代码：

# ### 1. 核心功能
# - **数据库存储**：将爬取的NGA论坛数据持久化到数据库
# - **数据分类处理**：区分用户(User)、主题(Topic)和回复(Reply)三类数据
# - **事务管理**：自动处理数据库事务提交和回滚
# - **资源管理**：管理数据库会话生命周期

# ### 2. 主要特性

# #### 数据库集成
# - 使用SQLAlchemy ORM框架
# - 支持三种数据模型：
#   - User(用户信息)
#   - Topic(主题帖)
#   - Reply(回复帖)
# - 采用merge操作实现"存在则更新，不存在则插入"逻辑

# #### 数据处理流程
# 1. 根据item类型路由到对应的处理方法
# 2. 将item数据转换为ORM模型对象
# 3. 执行数据库合并操作(merge)
# 4. 提交事务或出错时回滚

# #### 错误处理
# - 捕获SQLAlchemyError数据库异常
# - 出错时自动回滚事务
# - 记录详细的错误日志
# - 会话关闭异常处理

# #### 生命周期管理
# - 爬虫启动时创建数据库会话(open_spider)
# - 爬虫关闭时安全关闭会话(close_spider)
# - 保证会话资源正确释放

# ### 3. 数据模型处理细节

# #### 用户(User)处理
# - 必需字段：uid
# - 可选字段：
#   - user_group(默认值"匿名用户")
#   - reg_date
#   - prestige
#   - history_re_num

# #### 主题(Topic)处理
# - 必需字段：
#   - tid
#   - title
#   - poster_id
#   - post_time
#   - re_num
#   - sampling_time
# - 可选字段：
#   - last_reply_date
#   - partition

# #### 回复(Reply)处理
# - 必需字段：
#   - rid
#   - tid
#   - content
#   - poster_id
#   - post_time
#   - sampling_time
# - 可选字段：
#   - parent_rid(父回复ID)
#   - recommendvalue(默认值"0")

# ### 4. 关键方法

# 1. **核心方法**:
#    - `process_item`: 处理item的主入口
#    - `open_spider`: 初始化数据库会话
#    - `close_spider`: 清理资源

# 2. **数据处理方法**:
#    - `_process_user`: 处理用户数据
#    - `_process_topic`: 处理主题数据
#    - `_process_reply`: 处理回复数据

# ### 5. 技术细节
# - 使用SQLAlchemy的merge操作实现upsert功能
# - 采用显式事务管理(commit/rollback)
# - 通过isinstance检查item类型
# - 合理的默认值处理(如匿名用户、推荐值0)

# ### 6. 异常处理策略
# - 数据库操作统一捕获SQLAlchemyError
# - 出错时立即回滚当前事务
# - 记录错误日志但不中断流程
# - 资源关闭异常处理

# ### 7. 依赖组件
# - 数据库模型定义(models.py):
#   - User/Topic/Reply类
# - 数据库工具(db_utils.py):
#   - create_db_session函数
# - Item定义(items.py):
#   - UserItem/TopicItem/ReplyItem

# ### 8. 待优化点
# - 批量插入/更新支持
# - 异步数据库操作
# - 更细粒度的错误分类处理
# - 数据库连接池配置
# - 性能监控指标

import os
import scrapy
from sqlalchemy.exc import SQLAlchemyError
import hashlib
from scrapy.utils.python import to_bytes
from urllib.parse import urlparse
from scrapy.pipelines.images import ImagesPipeline
from scrapy.exceptions import DropItem

from . import settings
from .models import User, Topic, Reply
from .utils.db_utils import create_db_session
from .items import UserItem,TopicItem,ReplyItem
from scrapy.pipelines.images import ImagesPipeline

class NgaPipeline:
    def __init__(self):
        self.session = None

    def open_spider(self, spider):
        self.session = create_db_session()

    def close_spider(self, spider):
        if self.session:
            try:
                self.session.close()
            except Exception as e:
                spider.logger.error(f"Error closing session: {e}")

    def process_item(self, item, spider):
        try:
            if isinstance(item, UserItem):
                self._process_user(item)
            elif isinstance(item, TopicItem):
                self._process_topic(item)
            elif isinstance(item, ReplyItem):
                self._process_reply(item)
            self.session.commit()
        except SQLAlchemyError as e:
            self.session.rollback()
            spider.logger.error(f"Database error: {e}")
        return item

    def _process_user(self, item):
        user = User(
            uid=item['uid'],
            user_group=item.get('user_group', '匿名用户'),
            reg_date=item.get('reg_date'),
            prestige=item.get('prestige'),
            history_re_num=item.get('history_re_num')
        )
        self.session.merge(user)

    def _process_topic(self, item):
        topic = Topic(
            tid=item['tid'],
            title=item['title'],
            poster_id=item['poster_id'],
            post_time=item['post_time'],
            re_num=item['re_num'],
            sampling_time=item['sampling_time'],
            last_reply_date=item.get('last_reply_date'),
            partition=item.get('partition')
        )
        self.session.merge(topic)

    def _process_reply(self, item):
        reply = Reply(
            rid=item['rid'],
            tid=item['tid'],
            parent_rid=item.get('parent_rid'),
            content=item['content'],
            recommendvalue=item.get('recommendvalue', '0'),
            poster_id=item['poster_id'],
            post_time=item['post_time'],
            sampling_time=item['sampling_time'],
            image_urls=item.get('image_urls', []),
            image_paths=[
                os.path.join(settings.IMAGES_STORE, path)
                for path in item.get('images', [])
            ]
        )
        self.session.merge(reply)


class ImageDownloadPipeline(ImagesPipeline):

    headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://ngabbs.com/read.php?tid=43950064&page=7',
    },

    def get_media_requests(self, item, info):
        # 从item中获取图片URL
        if 'image_urls' in item and len(item['image_urls']) != 0:
            for image_url in item['image_urls']:
                try:
                    yield scrapy.Request(url=image_url)
                except Exception as e:
                    raise DropItem(f"Error processing image URL {image_url}: {str(e)}")

    def file_path(self, request, response=None, info=None, *, item=None):
        if 'image_urls' in item and len(item['image_urls']) != 0:
        # 生成文件名: 使用原始URL的MD5哈希值
            image_guid = hashlib.sha1(to_bytes(request.url)).hexdigest()
            return f'{image_guid}.jpg'
    
    def item_completed(self, results, item, info):
        if 'image_urls' in item and len(item['image_urls']) != 0:
            # 处理下载完成的图片
            image_paths = [x['path'] for ok, x in results if ok]
            if not image_paths:
                raise DropItem(f"image_paths:{image_paths}")
            item['image_paths'] = image_paths
            return item
