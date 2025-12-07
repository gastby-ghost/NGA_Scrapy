"""数据库工具模块 - PostgreSQL版本"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from ..models import Base
import logging

def create_db_session(db_url=None):
    """
    创建PostgreSQL数据库会话

    参数:
        db_url (str): 数据库连接URL。如果为None，则使用database_config中的配置

    返回:
        Session: SQLAlchemy会话对象
    """
    logger = logging.getLogger(__name__)
    
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
            
            # 🔍 添加详细的数据库连接诊断日志
            logger.info("🔍 [数据库连接诊断] 开始创建数据库连接")
            logger.info(f"🔍 [数据库连接诊断] 连接URL: {db_url.replace(db_url.split('@')[1].split(':')[0], '***') if '@' in db_url else db_url}")
            logger.info(f"🔍 [数据库连接诊断] 引擎参数: {engine_args}")
            
            # 测试基本连接
            try:
                test_engine = create_engine(db_url, connect_args={'connect_timeout': 10})
                with test_engine.connect() as test_conn:
                    logger.info("✅ [数据库连接诊断] 基本连接测试成功")
            except Exception as test_e:
                logger.error(f"❌ [数据库连接诊断] 基本连接测试失败: {test_e}")
                raise test_e
            
            engine = create_engine(db_url, **engine_args)
            
            # 测试连接池
            try:
                with engine.connect() as conn:
                    logger.info("✅ [数据库连接诊断] 连接池测试成功")
            except Exception as pool_e:
                logger.error(f"❌ [数据库连接诊断] 连接池测试失败: {pool_e}")
                raise pool_e
        else:
            logger.info(f"🔍 [数据库连接诊断] 使用自定义URL: {db_url}")
            engine = create_engine(db_url)

        Base.metadata.bind = engine
        Session = sessionmaker(bind=engine)
        session = Session()
        logger.info("✅ [数据库连接诊断] 会话创建成功")
        return session
        
    except SQLAlchemyError as e:
        logger.error(f"❌ [数据库连接错误] SQLAlchemy错误: {e}")
        logger.error(f"❌ [数据库连接错误] 错误类型: {type(e).__name__}")
        import traceback
        logger.error(f"❌ [数据库连接错误] 详细堆栈: {traceback.format_exc()}")
        return None
    except Exception as e:
        logger.error(f"❌ [数据库连接错误] 通用错误: {e}")
        logger.error(f"❌ [数据库连接错误] 错误类型: {type(e).__name__}")
        import traceback
        logger.error(f"❌ [数据库连接错误] 详细堆栈: {traceback.format_exc()}")
        return None
