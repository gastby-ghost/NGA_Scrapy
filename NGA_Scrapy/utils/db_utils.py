"""数据库工具模块"""
#db_utils.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from ..models import Base

def create_db_session(db_url=None):
    """
    创建数据库会话
    
    参数:
        db_url (str): 数据库连接URL。如果为None，则使用默认配置
        
    返回:
        Session: SQLAlchemy会话对象
    """
    try:
        if not db_url:
            db_url = "sqlite:///nga.db"
        engine = create_engine(db_url)
        Base.metadata.bind = engine
        Session = sessionmaker(bind=engine)
        return Session()
    except SQLAlchemyError as e:
        print(f"数据库连接错误: {e}")
        return None
