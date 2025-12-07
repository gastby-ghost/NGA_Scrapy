"""
动态代理管理模块
用于从巨量IP API获取和管理代理列表
"""
import hashlib
import json
import time
import logging
import requests
from typing import List, Optional, Dict
from datetime import datetime
import random


class ProxyManager:
    """动态代理管理器"""

    def __init__(self, config: Dict):
        """
        初始化代理管理器

        Args:
            config: 配置字典，包含以下键：
                - trade_no: 业务编号（必填）
                - api_key: API密钥（必填）
                - api_url: API地址（可选，默认为巨量IP的地址）
                - num: 单次提取数量（可选，默认10）
                - pt: 代理类型（可选，1=HTTP，默认1）
                - result_type: 返回类型（可选，默认json）
                - min_proxies: 最小代理数量阈值，低于此数量时自动获取（可选，默认5）
                - get_interval: 获取代理的最小间隔（秒）（可选，默认60）
        """
        # 验证必需参数
        self.trade_no = config.get('trade_no')
        self.api_key = config.get('api_key')

        if not self.trade_no or self.trade_no in ['your_trade_no_here', '']:
            raise ValueError("配置错误：trade_no是必填参数，且不能为默认值'your_trade_no_here'")

        if not self.api_key or self.api_key in ['your_api_key_here', '']:
            raise ValueError("配置错误：api_key是必填参数，且不能为默认值'your_api_key_here'")

        self.api_url = config.get('api_url', 'http://v2.api.juliangip.com/dynamic/getips')
        # 在云服务器上建议获取更多代理
        self.num = config.get('num', 20)
        self.pt = config.get('pt', 1)  # 1=HTTP代理
        self.result_type = config.get('result_type', 'json')
        # 在云服务器上设置更高的最小阈值，避免频繁获取
        self.min_proxies = config.get('min_proxies', 10)
        self.get_interval = config.get('get_interval', 60)
        # 重试配置
        self.max_retries = config.get('max_retries', 3)
        self.retry_interval = config.get('retry_interval', 2)
        # 可选参数
        self.auto_white = config.get('auto_white')
        self.split = config.get('split')

        # 代理池
        self.proxy_pool: List[str] = []
        self._last_get_time = 0
        self._used_proxies: set = set()
        self._failed_proxies: set = set()

        # 统计信息
        self.stats = {
            'total_fetched': 0,
            'total_failed': 0,
            'last_fetch_count': 0,
            'last_error': None
        }

        # 日志
        self.logger = logging.getLogger(__name__)

        self.logger.debug(f"代理管理器已初始化 - API: {self.api_url}, 提取数量: {self.num}, 最小代理数: {self.min_proxies}")

    def _generate_sign(self) -> str:
        """
        生成MD5签名
        根据巨量IP文档：sign = MD5(user_id + api_key)
        如果api_key已经是32位MD5格式，则直接返回

        Returns:
            签名字符串
        """
        # 检查api_key是否已经是MD5格式（32位十六进制字符串）
        if len(self.api_key) == 32 and all(c in '0123456789abcdef' for c in self.api_key.lower()):
            # 如果api_key已经是MD5格式，直接返回
            return self.api_key

        # 否则，使用trade_no和api_key生成MD5签名
        sign_str = f"{self.trade_no}{self.api_key}"
        return hashlib.md5(sign_str.encode('utf-8')).hexdigest()

    def get_proxies(self, force_refresh: bool = False) -> List[str]:
        """
        获取代理列表

        Args:
            force_refresh: 是否强制刷新代理列表

        Returns:
            代理列表
        """
        current_time = time.time()

        # 检查是否需要刷新代理
        if not force_refresh:
            # 如果代理池中有足够代理且未达到刷新间隔，则直接返回
            if (len(self.proxy_pool) >= self.min_proxies and
                current_time - self._last_get_time < self.get_interval):
                self.logger.debug(f"使用缓存代理池，当前有 {len(self.proxy_pool)} 个代理")
                return self.proxy_pool

        # 获取新代理
        self.logger.debug(f"正在从 API 获取代理，force_refresh={force_refresh}")
        try:
            proxies = self._fetch_proxies_from_api()
            if proxies:
                self.proxy_pool = proxies
                self._used_proxies.clear()  # 清除已使用记录
                # 移除失败的代理
                self._failed_proxies.clear()
                self._last_get_time = current_time

                # 更新统计信息
                self.stats['total_fetched'] += 1
                self.stats['last_fetch_count'] = len(proxies)
                self.stats['last_error'] = None

                self.logger.debug(f"✅ 成功获取 {len(proxies)} 个代理 (总计获取: {self.stats['total_fetched']} 次)")
                return self.proxy_pool
            else:
                # 未获取到代理，保留现有代理池
                self.stats['total_failed'] += 1
                self.logger.warning("⚠️ 未获取到任何代理，保留现有代理池")
                return self.proxy_pool if self.proxy_pool else []
        except Exception as e:
            self.stats['total_failed'] += 1
            self.stats['last_error'] = str(e)
            self.logger.error(f"❌ 获取代理失败，保留现有代理池: {str(e)}")
            return self.proxy_pool if self.proxy_pool else []

    def _fetch_proxies_from_api(self) -> Optional[List[str]]:
        """
        从API获取代理

        Returns:
            代理列表，失败返回None
        """
        # 构建请求参数
        params = {
            'trade_no': self.trade_no,
            'num': self.num,
            'pt': self.pt,
            'result_type': self.result_type,
            'sign': self._generate_sign()
        }

        # 添加可选参数
        if hasattr(self, 'auto_white'):
            params['auto_white'] = self.auto_white
        if hasattr(self, 'split'):
            params['split'] = self.split

        # 尝试多次获取代理
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    self.logger.debug(f"🔄 第 {attempt + 1} 次重试获取代理...")
                    time.sleep(self.retry_interval)

                self.logger.debug(f"正在调用代理API: {self.api_url}")
                self.logger.debug(f"请求参数: {params}")

                response = requests.get(
                    self.api_url,
                    params=params,
                    timeout=10
                )

                self.logger.debug(f"API响应状态码: {response.status_code}")
                self.logger.debug(f"API响应内容: {response.text[:500]}")

                response.raise_for_status()

                # 处理不同响应格式
                if self.result_type == 'text':
                    # 纯文本格式，每行一个代理
                    proxy_list = []
                    for line in response.text.strip().split('\n'):
                        line = line.strip()
                        if line:
                            proxy_list.append(line)
                    self.logger.debug(f"API返回文本格式: 代理列表={len(proxy_list)}")

                    # 检查是否获取到有效代理
                    if proxy_list:
                        # 验证代理格式（必须包含IP:PORT）
                        valid_proxies = []
                        for proxy in proxy_list:
                            if ':' in proxy:
                                valid_proxies.append(proxy)
                            else:
                                self.logger.warning(f"代理格式不正确，已过滤: {proxy}")

                        if valid_proxies:
                            return valid_proxies
                        elif attempt < self.max_retries - 1:
                            self.logger.warning(f"未获取到有效代理，准备第 {attempt + 2} 次重试")
                            continue
                        else:
                            self.logger.warning("已达到最大重试次数，返回空列表")
                            return []
                else:
                    # JSON格式
                    data = response.json()

                    if data.get('code') != 200:
                        error_msg = data.get('msg', '未知错误')
                        self.logger.error(f"API返回错误: {error_msg}")

                        # 如果是特定错误且还有重试次数，则重试
                        if ('未检索到满足要求的代理IP' in error_msg or
                            '调整筛选条件后再试' in error_msg) and attempt < self.max_retries - 1:
                            self.logger.warning(f"检测到代理不足错误，准备第 {attempt + 2} 次重试")
                            continue
                        else:
                            return None

                    # 提取代理列表
                    proxy_list = data.get('data', {}).get('proxy_list', [])
                    count = data.get('data', {}).get('count', 0)
                    surplus = data.get('data', {}).get('surplus_quantity', 0)

                    self.logger.debug(f"API返回: 总数={count}, 剩余={surplus}, 代理列表={len(proxy_list)}")

                    return proxy_list

            except requests.RequestException as e:
                self.logger.error(f"API请求失败: {str(e)}")
                if attempt == self.max_retries - 1:
                    return None
                continue
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON解析失败: {str(e)}")
                if attempt == self.max_retries - 1:
                    return None
                continue
            except Exception as e:
                self.logger.error(f"获取代理时发生未知错误: {str(e)}")
                if attempt == self.max_retries - 1:
                    return None
                continue

        return None

    def get_random_proxy(self, mark_used: bool = True) -> Optional[Dict]:
        """
        获取一个随机代理（带认证信息）

        Args:
            mark_used: 是否标记代理为已使用（用于请求时），默认True
                       浏览器池初始化时可以设为False以避免过早标记

        Returns:
            代理字典，包含proxy（ip:port）、username、password等字段
        """
        if not self.proxy_pool:
            # 如果没有代理，尝试获取
            self.get_proxies(force_refresh=True)
            if not self.proxy_pool:
                return None

        # 过滤未使用的代理
        available_proxies = [p for p in self.proxy_pool if p not in self._used_proxies]

        # 如果所有代理都已使用，清空记录或重新获取
        if not available_proxies:
            if len(self.proxy_pool) < self.min_proxies:
                self.logger.debug("代理池数量不足，重新获取")
                self.get_proxies(force_refresh=True)
                available_proxies = self.proxy_pool
            else:
                # 重置已使用记录（环形使用）
                self._used_proxies.clear()
                available_proxies = self.proxy_pool

        if not available_proxies:
            return None

        # 随机选择一个代理
        proxy_str = random.choice(available_proxies)

        # 只有在需要时，才标记为已使用
        if mark_used:
            self._used_proxies.add(proxy_str)

        # 解析代理格式：ip:port 或 ip:port,username,password
        proxy_dict = self._parse_proxy_string(proxy_str)

        return proxy_dict

    def _parse_proxy_string(self, proxy_str: str) -> Dict:
        """
        解析代理字符串

        支持格式：
        - ip:port
        - ip:port,username,password
        - ip:port,城市信息
        - ip:port,城市信息,邮政编号

        Args:
            proxy_str: 代理字符串

        Returns:
            代理字典
        """
        parts = proxy_str.split(',')

        # 解析IP和端口
        ip_port = parts[0].strip()
        if ':' not in ip_port:
            self.logger.warning(f"代理格式不正确: {proxy_str}")
            return {}

        ip, port = ip_port.split(':')

        proxy_dict = {
            'proxy': f'{ip}:{port}',
            'server': ip,
            'port': int(port),
        }

        # 如果有认证信息
        if len(parts) >= 3 and parts[1] and parts[2]:
            proxy_dict['username'] = parts[1]
            proxy_dict['password'] = parts[2]

        return proxy_dict

    def mark_proxy_failed(self, proxy_dict: Dict):
        """
        标记代理失败，将从代理池中移除

        Args:
            proxy_dict: 代理字典
        """
        proxy = proxy_dict.get('proxy')
        if proxy in self.proxy_pool:
            self.proxy_pool.remove(proxy)
            self._failed_proxies.add(proxy)
            self.logger.warning(f"❌ 代理 {proxy} 标记为失败，已从池中移除")

    def test_proxy_connectivity(self, proxy_dict: Dict, timeout: int = 10) -> Dict:
        """
        测试代理连通性（参考测试脚本实现）

        Args:
            proxy_dict: 代理字典
            timeout: 超时时间（秒）

        Returns:
            测试结果字典，包含 success、elapsed、error 等字段
        """
        result = {
            'success': False,
            'elapsed': 0,
            'error': None,
            'proxy': proxy_dict.get('proxy', 'unknown')
        }

        # 构建代理配置
        try:
            if proxy_dict.get('username') and proxy_dict.get('password'):
                proxy_url = f"http://{proxy_dict['username']}:{proxy_dict['password']}@{proxy_dict['server']}:{proxy_dict['port']}"
                proxies_conf = {
                    'http': proxy_url,
                    'https': proxy_url
                }
            else:
                proxy_url = f"{proxy_dict['server']}:{proxy_dict['port']}"
                proxies_conf = {
                    'http': proxy_url,
                    'https': proxy_url
                }

            start_time = time.time()
            try:
                import requests
                response = requests.get(
                    'http://httpbin.org/ip',
                    proxies=proxies_conf,
                    timeout=timeout
                )
                elapsed = time.time() - start_time

                if response.status_code == 200:
                    result['success'] = True
                    result['elapsed'] = elapsed
                    try:
                        ip_info = response.json()
                        result['proxy_ip'] = ip_info.get('origin', 'unknown')
                    except:
                        pass
                else:
                    result['error'] = f"HTTP {response.status_code}"
                    result['elapsed'] = elapsed

            except requests.exceptions.Timeout:
                result['elapsed'] = time.time() - start_time
                result['error'] = '连接超时'

            except requests.exceptions.ProxyError:
                result['error'] = '代理连接错误'

            except requests.exceptions.RequestException as e:
                result['error'] = f'请求错误: {str(e)[:100]}'

            except Exception as e:
                result['error'] = f'未知错误: {str(e)[:100]}'

        except Exception as e:
            result['error'] = f'代理配置错误: {str(e)}'

        return result

    def test_proxies(self, max_test: int = 3, timeout: int = 10) -> Dict:
        """
        测试多个代理的连通性（参考测试脚本）

        Args:
            max_test: 最大测试数量
            timeout: 超时时间（秒）

        Returns:
            测试结果摘要
        """
        self.logger.debug(f"🧪 开始测试代理连通性 (最多测试 {max_test} 个)")

        proxies = self.get_proxies()
        if not proxies:
            return {'error': '没有可用的代理进行测试'}

        success_count = 0
        failed_count = 0
        test_results = []

        for i in range(min(max_test, len(proxies))):
            proxy_dict = self.get_random_proxy()
            if not proxy_dict:
                continue

            test_result = self.test_proxy_connectivity(proxy_dict, timeout)
            test_results.append(test_result)

            if test_result['success']:
                success_count += 1
                self.logger.debug(f"  ✅ 测试 {i+1}/{min(max_test, len(proxies))}: {proxy_dict.get('proxy')} - 成功 (耗时: {test_result['elapsed']:.2f}s)")
                if 'proxy_ip' in test_result:
                    self.logger.debug(f"     代理IP: {test_result['proxy_ip']}")
            else:
                failed_count += 1
                self.logger.warning(f"  ❌ 测试 {i+1}/{min(max_test, len(proxies))}: {proxy_dict.get('proxy')} - 失败: {test_result['error']}")
                self.mark_proxy_failed(proxy_dict)

        summary = {
            'total_tested': len(test_results),
            'success_count': success_count,
            'failed_count': failed_count,
            'success_rate': success_count / len(test_results) * 100 if test_results else 0,
            'results': test_results
        }

        self.logger.info(f"📊 测试摘要: 成功 {success_count}, 失败 {failed_count}, 成功率 {summary['success_rate']:.1f}%")
        return summary

    def get_pool_status(self) -> Dict:
        """
        获取代理池状态（增强版）

        Returns:
            状态字典
        """
        return {
            'total_proxies': len(self.proxy_pool),
            'used_proxies': len(self._used_proxies),
            'available_proxies': len(self.proxy_pool) - len(self._used_proxies),
            'failed_proxies': len(self._failed_proxies),
            'last_fetch_time': datetime.fromtimestamp(self._last_get_time).strftime('%Y-%m-%d %H:%M:%S') if self._last_get_time > 0 else '未获取',
            'needs_refresh': len(self.proxy_pool) < self.min_proxies,
            'total_fetched': self.stats['total_fetched'],
            'total_failed': self.stats['total_failed'],
            'last_fetch_count': self.stats['last_fetch_count'],
            'last_error': self.stats['last_error']
        }

    def clear_pool(self):
        """清空代理池"""
        self.proxy_pool.clear()
        self._used_proxies.clear()
        self.logger.debug("代理池已清空")


# 全局代理管理器实例
_proxy_manager = None


def load_proxy_config(config_file: str = 'proxy_config.json') -> Dict:
    """
    从文件加载并验证代理配置（参考测试脚本实现）

    Args:
        config_file: 配置文件路径

    Returns:
        配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置格式或内容错误
    """
    import os
    import json

    # 如果配置文件不存在，尝试在项目根目录查找
    if not os.path.exists(config_file):
        # 获取当前文件的目录
        current_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        root_config = os.path.join(current_dir, 'proxy_config.json')
        if os.path.exists(root_config):
            config_file = root_config
        else:
            raise FileNotFoundError(f"配置文件不存在: {config_file}")

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"配置文件JSON格式错误: {e}")

    # 验证必需参数
    required_params = ['trade_no', 'api_key']
    missing_params = [p for p in required_params if not config.get(p) or
                     config.get(p) in ['your_trade_no_here', 'your_api_key_here', '']]

    if missing_params:
        raise ValueError(f"缺少必需参数或参数为默认值: {', '.join(missing_params)}")

    return config


def get_proxy_manager(config: Optional[Dict] = None, config_file: str = 'proxy_config.json') -> ProxyManager:
    """
    获取全局代理管理器实例（单例模式）

    Args:
        config: 配置字典，如果为None则尝试从配置文件加载
        config_file: 配置文件路径

    Returns:
        代理管理器实例
    """
    global _proxy_manager

    if _proxy_manager is None:
        if config is None:
            # 尝试从配置文件加载（参考测试脚本）
            config = load_proxy_config(config_file)

        _proxy_manager = ProxyManager(config)

    return _proxy_manager


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 示例配置（需要替换为真实的trade_no和api_key）
    test_config = {
        'trade_no': 'your_trade_no',
        'api_key': 'your_api_key',
        'num': 10,
        'result_type': 'json'
    }

    try:
        manager = ProxyManager(test_config)

        # 获取代理
        proxies = manager.get_proxies(force_refresh=True)
        print(f"获取到 {len(proxies)} 个代理")

        # 获取随机代理
        for i in range(3):
            proxy = manager.get_random_proxy()
            print(f"代理 {i+1}: {proxy}")

        # 查看状态
        status = manager.get_pool_status()
        print(f"\n代理池状态: {json.dumps(status, ensure_ascii=False, indent=2)}")

    except Exception as e:
        print(f"错误: {e}")
