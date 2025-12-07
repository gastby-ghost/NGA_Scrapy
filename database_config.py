# database_config.py
"""
PostgreSQL数据库配置管理
针对2核4G服务器优化
"""

import os
from typing import Optional

# 自动加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 如果没有安装python-dotenv，继续使用系统环境变量

# PostgreSQL配置
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'your_password'),
    'database': os.getenv('POSTGRES_DB', 'nga_scrapy'),
}

def get_database_url() -> str:
    """获取PostgreSQL数据库连接URL"""
    import logging
    logger = logging.getLogger(__name__)
    
    password = POSTGRES_CONFIG['password']
    # 如果密码包含特殊字符，需要URL编码
    from urllib.parse import quote
    encoded_password = quote(password, safe='')

    url = (
        f"postgresql://{POSTGRES_CONFIG['user']}:{encoded_password}"
        f"@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}"
        f"/{POSTGRES_CONFIG['database']}"
    )
    
    # 🔍 添加配置诊断日志
    logger.info(f"🔍 [配置诊断] 数据库配置:")
    logger.info(f"  - 主机: {POSTGRES_CONFIG['host']}")
    logger.info(f"  - 端口: {POSTGRES_CONFIG['port']}")
    logger.info(f"  - 用户: {POSTGRES_CONFIG['user']}")
    logger.info(f"  - 数据库: {POSTGRES_CONFIG['database']}")
    logger.info(f"  - 密码长度: {len(password)} 字符")
    logger.info(f"🔍 [配置诊断] 生成的URL: postgresql://{POSTGRES_CONFIG['user']}:***@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}")
    
    return url

def get_engine_args() -> dict:
    """获取PostgreSQL数据库引擎参数（针对2核4G服务器优化）"""
    return {
        'pool_size': 15,          # 连接池大小（2核4G推荐15-20）
        'max_overflow': 30,       # 超出池大小的连接数
        'pool_timeout': 30,       # 获取连接超时时间
        'pool_recycle': 3600,     # 连接回收时间（1小时）
        'echo': False,            # 是否打印SQL语句
        # 性能优化参数
        'pool_pre_ping': True,    # 启用连接预检
    }

def print_config():
    """打印当前数据库配置（不包含密码）"""
    print("\n" + "=" * 60)
    print("  PostgreSQL 数据库配置 (2核4G优化)")
    print("=" * 60)
    print(f"主机: {POSTGRES_CONFIG['host']}")
    print(f"端口: {POSTGRES_CONFIG['port']}")
    print(f"用户: {POSTGRES_CONFIG['user']}")
    print(f"数据库: {POSTGRES_CONFIG['database']}")
    print(f"连接池: {get_engine_args()['pool_size']} 基础连接 + {get_engine_args()['max_overflow']} 溢出连接")
    print(f"连接URL: {get_database_url().replace(POSTGRES_CONFIG['password'], '***')}")
    print("=" * 60 + "\n")
