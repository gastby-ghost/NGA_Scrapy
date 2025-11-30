"""数据库工具模块 - PostgreSQL版本"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from ..models import Base

def create_db_session(db_url=None):
    """
    创建PostgreSQL数据库会话

    参数:
        db_url (str): 数据库连接URL。如果为None，则使用database_config中的配置

    返回:
        Session: SQLAlchemy会话对象
    """
    try:
        if not db_url:
            # 使用database_config中的配置
            import sys
            import os
            # 添加项目根目录到Python路径
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from database_config import get_database_url, get_engine_args

            db_url = get_database_url()
            engine_args = get_engine_args()
            engine = create_engine(db_url, **engine_args)
        else:
            engine = create_engine(db_url)

        Base.metadata.bind = engine
        Session = sessionmaker(bind=engine)
        return Session()
    except SQLAlchemyError as e:
        print(f"数据库连接错误: {e}")
        import traceback
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"创建数据库会话时发生错误: {e}")
        import traceback
        traceback.print_exc()
        return None
