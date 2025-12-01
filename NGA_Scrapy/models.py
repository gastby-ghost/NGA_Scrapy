# models.py
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint,JSON
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
    partition=Column(String(50))  

class Reply(Base):
    __tablename__ = 'reply'
    __table_args__ = (
        UniqueConstraint('rid', name='uq_reply_rid'),
    )
    
    rid = Column(String(20), primary_key=True)
    tid = Column(String(20), ForeignKey('topic.tid'))
    parent_rid = Column(String(20))
    content = Column(Text)
    recommendvalue = Column(Integer)
    poster_id = Column(String(20), ForeignKey('user.uid'))
    post_time = Column(String(50))
    image_urls = Column(JSON)  # 新增：原始图片URL列表
    image_paths = Column(JSON)  # 新增：本地存储路径列表
    sampling_time = Column(String(50))
    
    topic = relationship("Topic")
    user = relationship("User")
    parent = relationship("Reply", remote_side=[rid])
