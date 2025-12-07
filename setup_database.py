#!/usr/bin/env python3
"""
数据库初始化和配置脚本
用于设置PostgreSQL数据库连接参数并确保系统配置一致
"""

import os
import sys
import logging
import subprocess
from getpass import getpass

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def check_postgres_status():
    """检查PostgreSQL服务状态"""
    logger.info("🔍 检查PostgreSQL服务状态...")
    try:
        result = subprocess.run(['sudo', '-u', 'postgres', 'pg_isready'], 
                          capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info("✅ PostgreSQL服务正在运行")
            # 提取端口信息
            if "accepting connections" in result.stdout:
                port_info = result.stdout.strip()
                logger.info(f"📍 端口信息: {port_info}")
                return True, port_info
        else:
            logger.error(f"❌ PostgreSQL服务异常: {result.stderr}")
            return False, None
    except Exception as e:
        logger.error(f"❌ 检查PostgreSQL状态失败: {e}")
        return False, None

def get_postgres_config():
    """获取PostgreSQL实际配置"""
    logger.info("🔍 获取PostgreSQL配置信息...")
    try:
        # 获取端口配置
        port_cmd = ["sudo", "-u", "postgres", "psql", "-c", "SHOW port;"]
        port_result = subprocess.run(port_cmd, capture_output=True, text=True, timeout=10)
        
        # 获取监听地址
        listen_cmd = ["sudo", "-u", "postgres", "psql", "-c", "SHOW listen_addresses;"]
        listen_result = subprocess.run(listen_cmd, capture_output=True, text=True, timeout=10)
        
        # 获取最大连接数
        max_conn_cmd = ["sudo", "-u", "postgres", "psql", "-c", "SHOW max_connections;"]
        max_conn_result = subprocess.run(max_conn_cmd, capture_output=True, text=True, timeout=10)
        
        config = {}
        if port_result.returncode == 0:
            port_lines = [line.strip() for line in port_result.stdout.strip().split('\n') if line.strip()]
            config['port'] = port_lines[-1] if port_lines else '5432'
        if listen_result.returncode == 0:
            listen_lines = [line.strip() for line in listen_result.stdout.strip().split('\n') if line.strip()]
            config['listen_addresses'] = listen_lines[-1] if listen_lines else 'localhost'
        if max_conn_result.returncode == 0:
            conn_lines = [line.strip() for line in max_conn_result.stdout.strip().split('\n') if line.strip()]
            config['max_connections'] = conn_lines[-1] if conn_lines else '100'
            
        logger.info(f"📊 PostgreSQL配置: {config}")
        return config
    except Exception as e:
        logger.error(f"❌ 获取PostgreSQL配置失败: {e}")
        return {}

def setup_database_user():
    """设置数据库用户和密码"""
    logger.info("👤 设置数据库用户...")
    
    # 检查用户是否存在
    check_user_cmd = ["sudo", "-u", "postgres", "psql", "-c", 
                    "SELECT usename FROM pg_user WHERE usename = 'nga_user';"]
    result = subprocess.run(check_user_cmd, capture_output=True, text=True, timeout=10)
    
    if result.returncode != 0:
        logger.error(f"❌ 检查用户失败: {result.stderr}")
        return False
    
    if "nga_user" not in result.stdout:
        # 创建用户
        logger.info("📝 创建新用户 nga_user...")
        create_user_cmd = ["sudo", "-u", "postgres", "psql", "-c", 
                        "CREATE USER nga_user WITH PASSWORD 'nga123';"]
        result = subprocess.run(create_user_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.error(f"❌ 创建用户失败: {result.stderr}")
            return False
        logger.info("✅ 用户 nga_user 创建成功")
    else:
        # 更新密码
        logger.info("🔄 更新用户密码...")
        update_pwd_cmd = ["sudo", "-u", "postgres", "psql", "-c", 
                       "ALTER USER nga_user WITH PASSWORD 'nga123';"]
        result = subprocess.run(update_pwd_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.error(f"❌ 更新密码失败: {result.stderr}")
            return False
        logger.info("✅ 密码更新成功")
    
    return True

def setup_database():
    """设置数据库"""
    logger.info("🗄️ 设置数据库...")
    
    # 检查数据库是否存在
    check_db_cmd = ["sudo", "-u", "postgres", "psql", "-c", 
                   "SELECT datname FROM pg_database WHERE datname = 'nga_scrapy';"]
    result = subprocess.run(check_db_cmd, capture_output=True, text=True, timeout=10)
    
    if result.returncode != 0:
        logger.error(f"❌ 检查数据库失败: {result.stderr}")
        return False
    
    if "nga_scrapy" not in result.stdout:
        # 创建数据库
        logger.info("📝 创建数据库 nga_scrapy...")
        create_db_cmd = ["sudo", "-u", "postgres", "psql", "-c", 
                       "CREATE DATABASE nga_scrapy OWNER nga_user;"]
        result = subprocess.run(create_db_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.error(f"❌ 创建数据库失败: {result.stderr}")
            return False
        logger.info("✅ 数据库 nga_scrapy 创建成功")
    else:
        logger.info("✅ 数据库 nga_scrapy 已存在")
    
    # 授权
    logger.info("🔐 设置数据库权限...")
    grant_cmd = ["sudo", "-u", "postgres", "psql", "-c", 
                "GRANT ALL PRIVILEGES ON DATABASE nga_scrapy TO nga_user;"]
    result = subprocess.run(grant_cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        logger.error(f"❌ 设置权限失败: {result.stderr}")
        return False
    logger.info("✅ 数据库权限设置成功")
    
    return True

def update_env_file(port):
    """更新.env文件"""
    logger.info("📝 更新环境配置文件...")
    
    env_content = f"""# PostgreSQL数据库配置
POSTGRES_HOST=localhost
POSTGRES_PORT={port}
POSTGRES_USER=nga_user
POSTGRES_PASSWORD=nga123
POSTGRES_DB=nga_scrapy
"""
    
    try:
        with open('.env', 'w') as f:
            f.write(env_content)
        logger.info("✅ .env 文件更新成功")
        return True
    except Exception as e:
        logger.error(f"❌ 更新.env文件失败: {e}")
        return False

def test_connection():
    """测试数据库连接"""
    logger.info("🧪 测试数据库连接...")
    
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='localhost',
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            user='nga_user',
            password='nga123',
            database='nga_scrapy',
            connect_timeout=10
        )
        logger.info("✅ 数据库连接测试成功")
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ 数据库连接测试失败: {e}")
        return False

def main():
    """主函数"""
    logger.info("🚀 开始数据库初始化和配置...")
    logger.info("=" * 60)
    
    # 1. 检查PostgreSQL服务
    service_ok, port_info = check_postgres_status()
    if not service_ok:
        logger.error("❌ PostgreSQL服务未运行，请先启动服务")
        return False
    
    # 2. 获取PostgreSQL配置
    pg_config = get_postgres_config()
    if not pg_config:
        logger.error("❌ 无法获取PostgreSQL配置")
        return False
    
    # 3. 设置数据库用户
    if not setup_database_user():
        logger.error("❌ 数据库用户设置失败")
        return False
    
    # 4. 设置数据库
    if not setup_database():
        logger.error("❌ 数据库设置失败")
        return False
    
    # 5. 更新环境配置文件
    # 从pg_isready输出中提取端口信息，或者使用已知的端口5433
    port = '5433'  # 默认使用我们已知的端口
    if 'port_info' in locals() and port_info:
        # 从 "/var/run/postgresql:5433 - accepting connections" 提取端口号
        import re
        port_match = re.search(r':(\d+)', port_info)
        if port_match:
            port = port_match.group(1)
    
    if not update_env_file(port):
        logger.error("❌ 环境配置文件更新失败")
        return False
    
    # 6. 测试连接
    os.environ['POSTGRES_PORT'] = port  # 设置环境变量用于测试
    if not test_connection():
        logger.error("❌ 数据库连接测试失败")
        return False
    
    logger.info("=" * 60)
    logger.info("✅ 数据库初始化和配置完成！")
    logger.info(f"📍 连接信息:")
    logger.info(f"   - 主机: localhost")
    logger.info(f"   - 端口: {port}")
    logger.info(f"   - 用户: nga_user")
    logger.info(f"   - 密码: nga123")
    logger.info(f"   - 数据库: nga_scrapy")
    logger.info("=" * 60)
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\n⚠️ 用户中断操作")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 未预期的错误: {e}")
        sys.exit(1)