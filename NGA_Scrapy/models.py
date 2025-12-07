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
