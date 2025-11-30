#!/usr/bin/env python3
"""
代理配置测试脚本
用于验证代理管理器和配置文件是否正确，并进行真实的代理获取和连通性测试
"""

import json
import sys
import os
import time
import requests

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'NGA_Scrapy'))

from utils.proxy_manager import ProxyManager


def test_proxy_config():
    """测试代理配置"""
    print("=" * 60)
    print("NGA_Scrapy 代理配置测试")
    print("=" * 60)

    # 检查配置文件是否存在
    config_file = 'proxy_config.json'
    if not os.path.exists(config_file):
        print(f"❌ 配置文件不存在: {config_file}")
        print(f"请复制模板文件: cp {config_file}.template {config_file}")
        print("然后编辑配置文件，填入真实的 trade_no 和 api_key")
        return False

    print(f"✅ 找到配置文件: {config_file}")

    # 读取配置
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print("✅ 配置文件格式正确")
    except json.JSONDecodeError as e:
        print(f"❌ 配置文件JSON格式错误: {e}")
        return False

    # 检查必需参数
    required_params = ['trade_no', 'api_key']
    missing_params = [p for p in required_params if not config.get(p) or config.get(p) == 'your_trade_no_here' or config.get(p) == 'your_api_key_here']

    if missing_params:
        print(f"❌ 缺少必需参数: {', '.join(missing_params)}")
        print("请在配置文件中填入真实的参数")
        return False

    print("✅ 必需参数已配置")

    # 显示配置信息
    print("\n📋 当前配置:")
    print(f"  业务编号 (trade_no): {config['trade_no']}")
    print(f"  API密钥 (api_key): {config.get('api_key')}")
    print(f"  API地址: {config.get('api_url', 'http://v2.api.juliangip.com/dynamic/getips')}")
    print(f"  提取数量: {config.get('num', 10)}")
    print(f"  代理类型: {'HTTP代理' if config.get('pt', 1) == 1 else 'SOCK代理'}")
    print(f"  返回格式: {config.get('result_type', 'json')}")

    # 测试代理管理器初始化
    print("\n🔧 正在初始化代理管理器...")
    try:
        manager = ProxyManager(config)
        print("✅ 代理管理器初始化成功")
    except Exception as e:
        print(f"❌ 代理管理器初始化失败: {e}")
        return False

    # 获取代理状态
    print("\n📊 代理池状态:")
    status = manager.get_pool_status()
    for key, value in status.items():
        print(f"  {key}: {value}")

    # 实际获取代理
    print("\n🔄 正在从 API 获取代理...")
    try:
        proxies = manager.get_proxies(force_refresh=True)
        if proxies:
            print(f"✅ 成功获取 {len(proxies)} 个代理")
            print("\n📋 代理列表:")
            for i, proxy in enumerate(proxies, 1):
                print(f"  {i}. {proxy}")
        else:
            print("⚠️  未获取到任何代理")
    except Exception as e:
        print(f"❌ 获取代理失败: {e}")

    # 测试代理连通性
    print("\n🧪 正在测试代理连通性...")
    success_count = 0
    failed_count = 0

    for i in range(min(3, len(proxies))):  # 最多测试3个代理
        proxy_dict = manager.get_random_proxy()
        if not proxy_dict:
            print(f"⚠️  跳过测试 {i+1}: 无法获取代理")
            continue

        print(f"\n  测试 {i+1}/{min(3, len(proxies))}: {proxy_dict.get('server')}:{proxy_dict.get('port')}")

        # 构建代理配置
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

        # 测试连通性
        start_time = time.time()
        try:
            response = requests.get(
                'http://httpbin.org/ip',
                proxies=proxies_conf,
                timeout=10
            )

            elapsed = time.time() - start_time

            if response.status_code == 200:
                ip_info = response.json()
                print(f"    ✅ 连接成功 (耗时: {elapsed:.2f}s)")
                print(f"    🌐 代理IP: {ip_info.get('origin', 'unknown')}")
                success_count += 1
            else:
                print(f"    ❌ 连接失败: HTTP {response.status_code}")
                failed_count += 1
                manager.mark_proxy_failed(proxy_dict)

        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            print(f"    ⏱️  连接超时 (耗时: {elapsed:.2f}s)")
            failed_count += 1
            manager.mark_proxy_failed(proxy_dict)

        except requests.exceptions.ProxyError as e:
            print(f"    ❌ 代理错误: 代理无法连接")
            failed_count += 1
            manager.mark_proxy_failed(proxy_dict)

        except requests.exceptions.RequestException as e:
            print(f"    ❌ 请求错误: {str(e)[:100]}")
            failed_count += 1
            manager.mark_proxy_failed(proxy_dict)

        except Exception as e:
            print(f"    ❌ 未知错误: {str(e)[:100]}")
            failed_count += 1
            manager.mark_proxy_failed(proxy_dict)

    # 测试摘要
    print("\n" + "=" * 60)
    print("📊 测试摘要:")
    print(f"  总测试数: {success_count + failed_count}")
    print(f"  成功: {success_count}")
    print(f"  失败: {failed_count}")
    print(f"  成功率: {success_count / (success_count + failed_count) * 100 if (success_count + failed_count) > 0 else 0:.1f}%")

    # 最终状态
    final_status = manager.get_pool_status()
    print("\n📊 最终代理池状态:")
    for key, value in final_status.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 60)
    if success_count > 0:
        print("✅ 代理配置测试完成 - 部分代理可用")
    else:
        print("⚠️  代理配置测试完成 - 无可用代理")
    print("=" * 60)

    return success_count > 0


if __name__ == '__main__':
    success = test_proxy_config()
    sys.exit(0 if success else 1)
