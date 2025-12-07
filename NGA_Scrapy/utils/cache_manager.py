#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存管理器模块

提供多层缓存系统，包括本地内存缓存和可选的Redis分布式缓存。
减少数据库查询次数，提升爬虫性能。

主要功能:
1. 本地内存缓存（LRU策略）
2. Redis分布式缓存（可选）
3. 缓存过期策略
4. 缓存命中率统计
5. 缓存预热功能

作者: Claude Code
日期: 2025-12-07
"""

import time
import json
import pickle
from datetime import datetime, timedelta
from collections import OrderedDict
from threading import Lock
import logging


class LocalCache:
    """本地内存缓存（LRU策略）"""

    def __init__(self, max_size=10000, ttl=3600):
        """初始化本地缓存

        Args:
            max_size: 最大缓存条目数
            ttl: 缓存过期时间（秒），默认1小时
        """
        self.max_size = max_size
        self.ttl = ttl
        self.cache = OrderedDict()  # 使用OrderedDict实现LRU
        self.lock = Lock()
        self.hits = 0
        self.misses = 0

    def _is_expired(self, timestamp):
        """检查缓存是否过期"""
        return time.time() - timestamp > self.ttl

    def get(self, key):
        """获取缓存值"""
        with self.lock:
            if key in self.cache:
                timestamp, value = self.cache[key]
                if not self._is_expired(timestamp):
                    # 移动到末尾（LRU）
                    self.cache.move_to_end(key)
                    self.hits += 1
                    return value
                else:
                    # 删除过期项
                    del self.cache[key]
            self.misses += 1
            return None

    def set(self, key, value):
        """设置缓存值"""
        with self.lock:
            # 如果键已存在，更新值并移动到末尾
            if key in self.cache:
                self.cache[key] = (time.time(), value)
                self.cache.move_to_end(key)
            else:
                # 如果超过最大容量，删除最旧的项
                if len(self.cache) >= self.max_size:
                    self.cache.popitem(last=False)
                self.cache[key] = (time.time(), value)

    def delete(self, key):
        """删除缓存项"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]

    def clear(self):
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0

    def get_stats(self):
        """获取缓存统计"""
        with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0
            return {
                'hits': self.hits,
                'misses': self.misses,
                'total': total,
                'hit_rate': hit_rate,
                'size': len(self.cache),
                'max_size': self.max_size,
            }

    def cleanup_expired(self):
        """清理过期缓存项"""
        with self.lock:
            expired_keys = []
            for key, (timestamp, _) in self.cache.items():
                if self._is_expired(timestamp):
                    expired_keys.append(key)

            for key in expired_keys:
                del self.cache[key]

            return len(expired_keys)


class RedisCache:
    """Redis分布式缓存（可选）"""

    def __init__(self, redis_config=None):
        """初始化Redis缓存

        Args:
            redis_config: Redis配置字典，包含host, port, password等
        """
        self.redis_config = redis_config or {}
        self.redis_client = None
        self.enabled = False

        try:
            import redis
            self.redis_client = redis.Redis(**redis_config)
            # 测试连接
            self.redis_client.ping()
            self.enabled = True
            logging.getLogger(__name__).info("Redis缓存连接成功")
        except ImportError:
            logging.getLogger(__name__).warning("Redis未安装，使用本地缓存")
        except Exception as e:
            logging.getLogger(__name__).warning(f"Redis连接失败: {e}，使用本地缓存")

    def get(self, key):
        """获取缓存值"""
        if not self.enabled:
            return None

        try:
            value = self.redis_client.get(key)
            if value is not None:
                return pickle.loads(value)
        except Exception as e:
            logging.getLogger(__name__).error(f"Redis获取缓存失败: {e}")

        return None

    def set(self, key, value, ttl=3600):
        """设置缓存值"""
        if not self.enabled:
            return False

        try:
            serialized_value = pickle.dumps(value)
            self.redis_client.setex(key, ttl, serialized_value)
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"Redis设置缓存失败: {e}")
            return False

    def delete(self, key):
        """删除缓存项"""
        if not self.enabled:
            return False

        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"Redis删除缓存失败: {e}")
            return False

    def clear(self):
        """清空缓存"""
        if not self.enabled:
            return False

        try:
            self.redis_client.flushdb()
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"Redis清空缓存失败: {e}")
            return False

    def get_stats(self):
        """获取缓存统计"""
        if not self.enabled:
            return {'enabled': False}

        try:
            info = self.redis_client.info()
            return {
                'enabled': True,
                'connected_clients': info.get('connected_clients'),
                'used_memory': info.get('used_memory'),
                'keyspace_hits': info.get('keyspace_hits'),
                'keyspace_misses': info.get('keyspace_misses'),
            }
        except Exception as e:
            logging.getLogger(__name__).error(f"获取Redis统计失败: {e}")
            return {'enabled': True, 'error': str(e)}


class CacheManager:
    """缓存管理器（统一本地和Redis缓存）"""

    def __init__(self, config=None):
        """初始化缓存管理器

        Args:
            config: 配置字典
                - local_cache: 本地缓存配置 {'max_size': 10000, 'ttl': 3600}
                - redis: Redis配置 {'host': 'localhost', 'port': 6379}
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)

        # 初始化本地缓存
        local_config = self.config.get('local_cache', {})
        self.local_cache = LocalCache(
            max_size=local_config.get('max_size', 10000),
            ttl=local_config.get('ttl', 3600)
        )

        # 初始化Redis缓存
        redis_config = self.config.get('redis', {})
        self.redis_cache = RedisCache(redis_config)

        # 缓存策略
        self.cache_strategy = self.config.get('strategy', 'local_first')  # local_first, redis_first, hybrid

        # 统计信息
        self.stats = {
            'local_hits': 0,
            'local_misses': 0,
            'redis_hits': 0,
            'redis_misses': 0,
            'total_gets': 0,
            'total_sets': 0,
        }

    def get(self, key):
        """获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值或None
        """
        self.stats['total_gets'] += 1

        # 本地优先策略
        if self.cache_strategy == 'local_first':
            value = self.local_cache.get(key)
            if value is not None:
                self.stats['local_hits'] += 1
                return value

            # 本地缓存未命中，尝试Redis
            if self.redis_cache.enabled:
                value = self.redis_cache.get(key)
                if value is not None:
                    self.stats['redis_hits'] += 1
                    # 回写到本地缓存
                    self.local_cache.set(key, value)
                    return value

            self.stats['local_misses'] += 1
            if self.redis_cache.enabled:
                self.stats['redis_misses'] += 1
            return None

        # Redis优先策略
        elif self.cache_strategy == 'redis_first':
            if self.redis_cache.enabled:
                value = self.redis_cache.get(key)
                if value is not None:
                    self.stats['redis_hits'] += 1
                    # 回写到本地缓存
                    self.local_cache.set(key, value)
                    return value

            # Redis未命中，尝试本地
            value = self.local_cache.get(key)
            if value is not None:
                self.stats['local_hits'] += 1
                return value

            self.stats['redis_misses'] += 1
            self.stats['local_misses'] += 1
            return None

        # 混合策略（同时写入两个缓存）
        else:
            # 先尝试本地
            value = self.local_cache.get(key)
            if value is not None:
                self.stats['local_hits'] += 1
                return value

            # 再尝试Redis
            if self.redis_cache.enabled:
                value = self.redis_cache.get(key)
                if value is not None:
                    self.stats['redis_hits'] += 1
                    return value

            self.stats['local_misses'] += 1
            if self.redis_cache.enabled:
                self.stats['redis_misses'] += 1
            return None

    def set(self, key, value, ttl=None):
        """设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None表示使用默认

        Returns:
            是否设置成功
        """
        self.stats['total_sets'] += 1

        # 写入本地缓存
        self.local_cache.set(key, value)

        # 写入Redis（如果启用）
        if self.redis_cache.enabled:
            ttl = ttl or self.config.get('local_cache', {}).get('ttl', 3600)
            self.redis_cache.set(key, value, ttl)

        return True

    def delete(self, key):
        """删除缓存项"""
        self.local_cache.delete(key)
        if self.redis_cache.enabled:
            self.redis_cache.delete(key)
        return True

    def clear(self):
        """清空所有缓存"""
        self.local_cache.clear()
        if self.redis_cache.enabled:
            self.redis_cache.clear()
        self.stats = {
            'local_hits': 0,
            'local_misses': 0,
            'redis_hits': 0,
            'redis_misses': 0,
            'total_gets': 0,
            'total_sets': 0,
        }

    def get_stats(self):
        """获取缓存统计信息"""
        local_stats = self.local_cache.get_stats()
        redis_stats = self.redis_cache.get_stats()

        # 计算总体命中率
        total_hits = self.stats['local_hits'] + self.stats['redis_hits']
        total_accesses = self.stats['total_gets']
        overall_hit_rate = (total_hits / total_accesses * 100) if total_accesses > 0 else 0

        return {
            'strategy': self.cache_strategy,
            'local_cache': local_stats,
            'redis_cache': redis_stats,
            'overall': {
                'total_hits': total_hits,
                'total_misses': self.stats['total_gets'] - total_hits,
                'total_gets': self.stats['total_gets'],
                'total_sets': self.stats['total_sets'],
                'hit_rate': overall_hit_rate,
            }
        }

    def cleanup_expired(self):
        """清理过期缓存项"""
        return self.local_cache.cleanup_expired()

    def warm_up(self, data_dict, ttl=None):
        """缓存预热

        Args:
            data_dict: 预热数据字典 {key: value}
            ttl: 过期时间
        """
        self.logger.info(f"开始缓存预热，共{len(data_dict)}项")
        for key, value in data_dict.items():
            self.set(key, value, ttl)
        self.logger.info("缓存预热完成")


# 便捷函数和全局实例
_cache_manager = None


def get_cache_manager(config=None):
    """获取全局缓存管理器实例"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(config)
    return _cache_manager


def cache_get(key):
    """便捷函数：获取缓存"""
    return get_cache_manager().get(key)


def cache_set(key, value, ttl=None):
    """便捷函数：设置缓存"""
    return get_cache_manager().set(key, value, ttl)


def cache_delete(key):
    """便捷函数：删除缓存"""
    return get_cache_manager().delete(key)


def get_cache_stats():
    """便捷函数：获取缓存统计"""
    return get_cache_manager().get_stats()


if __name__ == "__main__":
    # 测试代码
    config = {
        'local_cache': {'max_size': 1000, 'ttl': 60},
        'strategy': 'local_first',
    }

    cache = CacheManager(config)

    # 测试写入和读取
    cache.set('test_key', {'data': 'test_value'})
    value = cache.get('test_key')
    print(f"缓存值: {value}")

    # 测试统计
    stats = cache.get_stats()
    print(f"缓存统计: {json.dumps(stats, indent=2, ensure_ascii=False)}")

    # 测试LRU
    for i in range(100):
        cache.set(f'key_{i}', f'value_{i}')

    print(f"缓存大小: {len(cache.local_cache.cache)}")
