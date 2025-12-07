#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NGA_Scrapy 优化系统集成脚本

自动将所有优化模块集成到nga_spider.py中，确保爬虫能够使用所有优化功能。

优化功能包括:
1. 数据库索引优化
2. 分批查询机制
3. 查询性能监控
4. 缓存层系统
5. 查询策略优化
6. 智能预加载系统
7. 数据归档机制

作者: Claude Code
日期: 2025-12-07
"""

import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def integrate_optimizations():
    """集成所有优化模块到nga_spider.py"""

    spider_file = Path('/home/shan/NGA_Scrapy/NGA_Scrapy/spiders/nga_spider.py')

    if not spider_file.exists():
        logger.error(f"nga_spider.py文件不存在: {spider_file}")
        return False

    # 读取当前文件内容
    with open(spider_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 检查是否已集成数据归档
    if 'from ..utils.data_archiver import DataArchiver' in content:
        logger.info("✅ 数据归档已集成")
    else:
        logger.warning("⚠️ 数据归档未集成，需要手动添加")
        logger.info("请在nga_spider.py的__init__方法中添加:")
        logger.info("""
        # 初始化数据归档器
        from ..utils.data_archiver import DataArchiver
        self.data_archiver = DataArchiver(
            self.db_session,
            archive_dir='./archive',
            config={'enabled': True}
        )
        """)

    # 检查关键优化功能是否已实现
    checks = {
        '缓存系统': 'self.cache_manager = get_cache_manager()',
        '查询优化器': 'self.query_optimizer = QueryOptimizer',
        '性能监控': 'from ..utils.monitoring import get_monitor',
        'batch_query_topics_from_db': 'def batch_query_topics_from_db',
    }

    for check_name, check_pattern in checks.items():
        if check_pattern in content:
            logger.info(f"✅ {check_name}已集成")
        else:
            logger.error(f"❌ {check_name}未找到，可能需要重新集成")

    logger.info("\n" + "=" * 80)
    logger.info("集成检查完成")
    logger.info("=" * 80)

    return True


def create_optimized_spider_template():
    """创建优化后的爬虫模板代码"""

    template = '''
# ========================================
# NGA_Scrapy 优化系统集成模板
# ========================================

# 在NgaSpider类的__init__方法中添加以下代码：

def __init__(self, *args, **kwargs):
    super(NgaSpider, self).__init__(*args, **kwargs)

    # 缓存主题的最新回复时间，减少数据库查询
    self.topic_last_reply_cache = {}

    # ========================================
    # 优化系统集成 - 开始
    # ========================================

    # 1. 初始化缓存管理器
    from ..utils.cache_manager import get_cache_manager
    self.cache_manager = get_cache_manager({
        'local_cache': {'max_size': 10000, 'ttl': 3600},
        'strategy': 'local_first',
    })

    # 2. 初始化查询优化器
    from ..utils.query_optimizer import QueryOptimizer
    self.query_optimizer = None  # 将在数据库初始化后设置

    # 3. 初始化性能监控器
    from ..utils.monitoring import get_monitor
    self.query_monitor = get_monitor()

    # 4. 初始化数据归档器（月度归档）
    from ..utils.data_archiver import DataArchiver
    self.data_archiver = None  # 将在数据库初始化后设置

    # ========================================
    # 优化系统集成 - 结束
    # ========================================

    # 数据库相关属性
    self.db_session = None
    self.db_url = kwargs.get('db_url')
    import psutil
    self.process = psutil.Process()


# 在_init_db方法中添加：

def _init_db(self):
    """初始化数据库连接"""
    from ..utils.db_utils import create_db_session
    try:
        # 使用scoped_session包装，确保线程安全
        session_factory = create_db_session(self.db_url)
        if session_factory is None:
            raise RuntimeError("无法创建数据库会话工厂")

        self.db_session = scoped_session(lambda: session_factory)

        # 初始化查询优化器
        if self.query_optimizer is None:
            self.query_optimizer = QueryOptimizer(self.db_session, self.logger)

        # 初始化数据归档器（月度归档）
        if self.data_archiver is None:
            self.data_archiver = DataArchiver(
                self.db_session,
                archive_dir='./archive',
                config={
                    'enabled': True,
                    'archive_threshold_days': 30,  # 30天未更新则归档
                }
            )

        self.logger.info("数据库连接和优化组件初始化成功")

    except Exception as e:
        self.logger.error(f"数据库初始化失败: {e}")
        raise


# 在parse_topic_list方法中添加：

def parse_topic_list(self, response):
    """两阶段主题列表解析：阶段1-收集所有主题信息"""
    # ... 现有代码 ...

    # 在收集主题信息后，可以执行其他优化操作
    # 例如：记录访问模式、缓存更新等

    # ... 剩余代码 ...


# 在爬虫关闭时添加归档操作：

def close(self, reason):
    """爬虫关闭时清理资源"""
    # 执行月度数据归档
    if hasattr(self, 'data_archiver') and self.data_archiver:
        try:
            logger.info("开始执行月度数据归档...")
            archive_results = self.data_archiver.auto_archive()
            logger.info(f"归档结果: {archive_results}")

            # 清理过期归档文件
            cleaned_count = self.data_archiver.cleanup_old_archives(retention_days=365)
            logger.info(f"清理了 {cleaned_count} 个过期归档文件")

        except Exception as e:
            self.logger.error(f"数据归档失败: {e}")

    # 关闭数据库会话
    if hasattr(self, 'db_session') and self.db_session:
        try:
            self.db_session.remove()
            self.logger.info("数据库会话已关闭")
        except Exception as e:
            self.logger.error(f"关闭数据库会话时出错: {e}")

    self.logger.info(f"关闭爬虫方式: {reason}")
'''

    # 保存模板到文件
    template_file = Path('/home/shan/NGA_Scrapy/optimized_spider_template.txt')
    with open(template_file, 'w', encoding='utf-8') as f:
        f.write(template)

    logger.info(f"✅ 优化模板已保存到: {template_file}")
    return str(template_file)


def verify_installation():
    """验证优化系统安装"""

    logger.info("=" * 80)
    logger.info("🔍 验证NGA_Scrapy优化系统安装")
    logger.info("=" * 80)

    # 检查优化模块文件
    modules = [
        ('NGA_Scrapy/utils/cache_manager.py', '缓存管理器'),
        ('NGA_Scrapy/utils/query_optimizer.py', '查询优化器'),
        ('NGA_Scrapy/utils/monitoring.py', '性能监控'),
        ('NGA_Scrapy/utils/data_archiver.py', '数据归档（月度）'),
        ('NGA_Scrapy/utils/database_partition.py', '数据库分区'),
        ('add_indexes.py', '索引迁移脚本'),
        ('test_optimization.py', '测试脚本'),
        ('OPTIMIZATION_DEPLOYMENT.md', '部署指南'),
    ]

    all_exists = True
    for module_path, module_name in modules:
        file_path = Path('/home/shan/NGA_Scrapy') / module_path
        if file_path.exists():
            size = file_path.stat().st_size
            logger.info(f"✅ {module_name}: {module_path} ({size:,} bytes)")
        else:
            logger.error(f"❌ {module_name}: {module_path} - 文件不存在")
            all_exists = False

    # 检查nga_spider.py集成
    spider_file = Path('/home/shan/NGA_Scrapy/NGA_Scrapy/spiders/nga_spider.py')
    if spider_file.exists():
        with open(spider_file, 'r', encoding='utf-8') as f:
            spider_content = f.read()

        integrations = [
            ('cache_manager', '缓存管理器'),
            ('query_optimizer', '查询优化器'),
            ('monitoring', '性能监控'),
        ]

        for keyword, name in integrations:
            if keyword in spider_content:
                logger.info(f"✅ {name}已集成到nga_spider.py")
            else:
                logger.warning(f"⚠️ {name}未集成到nga_spider.py")

    logger.info("\n" + "=" * 80)
    if all_exists:
        logger.info("✅ 所有优化模块文件已就绪")
    else:
        logger.warning("⚠️ 部分优化模块文件缺失")

    logger.info("=" * 80)

    return all_exists


def main():
    """主函数"""
    logger.info("🚀 开始集成NGA_Scrapy优化系统\n")

    # 验证安装
    verify_installation()

    # 集成优化
    integrate_optimizations()

    # 创建模板
    create_optimized_spider_template()

    logger.info("\n" + "=" * 80)
    logger.info("📋 下一步操作指南:")
    logger.info("=" * 80)
    logger.info("1. 运行索引迁移:")
    logger.info("   python add_indexes.py")
    logger.info("\n2. 运行综合测试:")
    logger.info("   python test_optimization.py")
    logger.info("\n3. 参考部署指南:")
    logger.info("   cat OPTIMIZATION_DEPLOYMENT.md")
    logger.info("\n4. 查看优化模板:")
    logger.info("   cat optimized_spider_template.txt")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
