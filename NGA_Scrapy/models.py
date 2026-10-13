# models.py
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint, JSON, Index
from sqlalchemy.orm import relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'user'
    
    uid = Column(String(20), primary_key=True)
    name = Column(String(50))
    user_group = Column(String(50))
    prestige = Column(String(20))
    reg_date = Column(String(50))
    history_re_num = Column(String(20))

class Topic(Base):
    __tablename__ = 'topic'

    tid = Column(String(20), primary_key=True)
    title = Column(Text)
    poster_id = Column(String(20), ForeignKey('user.uid'))
    post_time = Column(String(50))
    re_num = Column(Integer)
    sampling_time = Column(String(50))
    last_reply_date = Column(String(50))
    partition = Column(String(50))

    # 数据库索引优化
    __table_args__ = (
        Index('idx_topic_last_reply_date', 'last_reply_date'),
        Index('idx_topic_post_time', 'post_time'),
        Index('idx_topic_poster_id', 'poster_id'),
        Index('idx_topic_re_num', 're_num'),
        Index('idx_topic_partition', 'partition'),
    )  

class Post(Base):
    """统一记录层（URB）：跨平台回复/帖子单元，**分析层唯一读取入口**。

    NGA 数据经 monitors/nga_sync.py 从 reply 表增量同步（reply/topic 是 NGA 采集器内部形态）；
    HN / Discourse 由 monitors 直接写入。新增平台时只加写入适配器，不改分析侧读取方式。

    字段口径：
    - unit_id：平台内全局唯一的楼/评论 ID（NGA rid / HN item id / Discourse "实例名:post_id"）
    - parent_id：回复关系指向的 unit_id；parent_carrier 说明关系写在正文（content，NGA）还是结构字段（structure，HN/Discourse）
    - post_time：UTC ISO8601（NGA 北京时间字符串由同步器转换；解析失败的保留原串）
    - content：原始内容（NGA=UBB 原文，HN/Discourse=HTML），content_format 标注格式，清洗留给分析层
    """
    __tablename__ = 'post'
    __table_args__ = (
        Index('idx_post_platform_thread', 'platform', 'thread_id'),
        Index('idx_post_platform_time', 'platform', 'post_time'),
    )

    platform = Column(String(20), primary_key=True)      # nga | hn | discourse
    unit_id = Column(String(40), primary_key=True)
    community = Column(String(100))                      # NGA 版块名 / Discourse 实例名 / 'hackernews'
    thread_id = Column(String(60), nullable=False)
    thread_title = Column(Text)
    parent_id = Column(String(40))
    parent_carrier = Column(String(10))                  # content | structure | none
    author = Column(String(100))
    post_time = Column(String(40))
    content = Column(Text)
    content_format = Column(String(10))                  # ubb | html
    recommend = Column(Integer)
    image_urls = Column(JSON)
    source_url = Column(Text)
    sampled_at = Column(String(40))                      # 首次采到
    last_seen = Column(String(40))                       # 最近一次刷新


class MonitorThread(Base):
    """监测清单：正在追踪的帖子及其状态（低影响护栏——每平台 max_tracking 控制规模）。

    status: tracking（活跃追踪）→ cooled（超活跃窗口，不再刷新）→ done（长期无活动，仅留档）
    """
    __tablename__ = 'monitor_thread'
    __table_args__ = (
        Index('idx_monitor_status', 'platform', 'status'),
    )

    platform = Column(String(20), primary_key=True)      # hn | discourse
    thread_id = Column(String(60), primary_key=True)
    community = Column(String(100))
    title = Column(Text)
    status = Column(String(20), default='tracking')
    unit_count = Column(Integer)
    discovered_at = Column(String(40))
    last_fetched_at = Column(String(40))
    last_activity_at = Column(String(40))                # 帖内最新楼时间（UTC ISO）


class Reply(Base):
    __tablename__ = 'reply'
    __table_args__ = (
        UniqueConstraint('rid', name='uq_reply_rid'),
        Index('idx_reply_tid_post_time', 'tid', 'post_time'),
        Index('idx_reply_poster_id', 'poster_id'),
        Index('idx_reply_post_time', 'post_time'),
        Index('idx_reply_recommendvalue', 'recommendvalue'),
    )

    rid = Column(String(20), primary_key=True)
    tid = Column(String(20), ForeignKey('topic.tid'))
    parent_rid = Column(String(20))
    content = Column(Text)
    recommendvalue = Column(Integer)
    poster_id = Column(String(20), ForeignKey('user.uid'))
    post_time = Column(String(50))
    image_urls = Column(JSON)
    image_paths = Column(JSON)
    sampling_time = Column(String(50))

    topic = relationship("Topic")
    user = relationship("User")
