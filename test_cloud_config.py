#!/usr/bin/env python3
"""
云服务器配置测试脚本
测试代理、数据库和系统资源是否满足运行条件
"""
import os
import sys
import json
import sqlite3
import psutil
from datetime import datetime

def print_header(title):
    """打印标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_result(status, message):
    """打印测试结果"""
    symbol = "✅" if status else "❌"
    print(f"{symbol}  {message}")

def test_python_version():
    """测试Python版本"""
    print_header("Python版本检查")
    version = sys.version_info
    print(f"当前版本: Python {version.major}.{version.minor}.{version.micro}")
    if version.major >= 3 and version.minor >= 8:
        print_result(True, "Python版本满足要求 (>=3.8)")
        return True
    else:
        print_result(False, "Python版本过低，需要 >=3.8")
        return False

def test_virtual_env():
    """测试虚拟环境"""
    print_header("虚拟环境检查")
    venv_path = os.environ.get('VIRTUAL_ENV')
    if venv_path:
        print_result(True, f"虚拟环境已激活: {venv_path}")
        return True
    else:
        print_result(False, "未检测到虚拟环境，请运行: source venv/bin/activate")
        return False

def test_dependencies():
    """测试依赖包"""
    print_header("依赖包检查")
    required_packages = [
        'scrapy', 'playwright', 'sqlalchemy', 'requests', 'psutil'
    ]

    all_ok = True
    for package in required_packages:
        try:
            __import__(package)
            print_result(True, f"{package} 已安装")
        except ImportError:
            print_result(False, f"{package} 未安装，请运行: pip install {package}")
            all_ok = False

    return all_ok

def test_playwright_browser():
    """测试Playwright浏览器"""
    print_header("Playwright浏览器检查")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto('https://httpbin.org/ip', timeout=10000)
            content = page.content()
            browser.close()
            print_result(True, "Playwright浏览器可正常使用")
            return True
    except Exception as e:
        print_result(False, f"Playwright浏览器测试失败: {str(e)[:50]}")
        return False

def test_database():
    """测试数据库"""
    print_header("数据库检查")

    # 检查是否存在数据库文件
    if os.path.exists('nga.db'):
        print_result(True, "数据库文件存在: nga.db")

        # 测试连接
        try:
            conn = sqlite3.connect('nga.db', timeout=5)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            conn.close()

            print_result(True, f"数据库连接正常，包含 {len(tables)} 个表")
            return True
        except Exception as e:
            print_result(False, f"数据库连接失败: {str(e)}")
            return False
    else:
        print_result(False, "数据库文件不存在，请运行: python init_db.py")
        return False

def test_proxy_config():
    """测试代理配置"""
    print_header("代理配置检查")

    # 检查配置文件
    if not os.path.exists('proxy_config.json'):
        print_result(False, "代理配置文件不存在: proxy_config.json")
        print("  解决方案: 1) 创建配置文件  2) 使用直连模式")
        return False

    # 读取配置
    try:
        with open('proxy_config.json', 'r') as f:
            config = json.load(f)

        # 检查必需字段
        if not config.get('trade_no') or config.get('trade_no') == 'your_trade_no_here':
            print_result(False, "trade_no未配置或为默认值")
            return False

        if not config.get('api_key') or config.get('api_key') == 'your_api_key_here':
            print_result(False, "api_key未配置或为默认值")
            return False

        print_result(True, "代理配置文件格式正确")

        # 测试代理连接
        try:
            from NGA_Scrapy.utils.proxy_manager import get_proxy_manager
            manager = get_proxy_manager(config)

            # 获取代理列表
            proxies = manager.get_proxies(force_refresh=True)

            if proxies and len(proxies) > 0:
                print_result(True, f"成功获取 {len(proxies)} 个代理")

                # 测试第一个代理
                proxy_dict = manager.get_random_proxy()
                if proxy_dict:
                    result = manager.test_proxy_connectivity(proxy_dict, timeout=5)
                    if result['success']:
                        print_result(True, f"代理测试成功，耗时: {result['elapsed']:.2f}s")
                        return True
                    else:
                        print_result(False, f"代理测试失败: {result['error']}")
                        return False
            else:
                print_result(False, "未获取到任何代理")
                return False

        except Exception as e:
            print_result(False, f"代理测试出错: {str(e)}")
            return False

    except json.JSONDecodeError:
        print_result(False, "代理配置文件JSON格式错误")
        return False
    except Exception as e:
        print_result(False, f"代理配置测试失败: {str(e)}")
        return False

def test_system_resources():
    """测试系统资源"""
    print_header("系统资源检查")

    # CPU
    cpu_count = psutil.cpu_count()
    print(f"CPU核心数: {cpu_count}")

    # 内存
    memory = psutil.virtual_memory()
    total_gb = memory.total / (1024**3)
    available_gb = memory.available / (1024**3)
    used_percent = memory.percent

    print(f"总内存: {total_gb:.1f}GB")
    print(f"可用内存: {available_gb:.1f}GB ({used_percent:.1f}%已使用)")

    # 磁盘
    disk = psutil.disk_usage('/')
    disk_free_gb = disk.free / (1024**3)
    print(f"磁盘剩余空间: {disk_free_gb:.1f}GB")

    # 评估
    issues = []
    if cpu_count < 2:
        issues.append("CPU核心数少于2个")

    if total_gb < 2:
        issues.append("总内存少于2GB")

    if used_percent > 80:
        issues.append("内存使用率超过80%")

    if disk_free_gb < 5:
        issues.append("磁盘剩余空间少于5GB")

    if issues:
        print_result(False, "系统资源不足:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print_result(True, "系统资源满足要求")
        return True

def test_cookies():
    """测试Cookies文件"""
    print_header("Cookies检查")

    if os.path.exists('cookies.txt'):
        try:
            with open('cookies.txt', 'r') as f:
                cookies = json.load(f)
            if isinstance(cookies, list) and len(cookies) > 0:
                print_result(True, f"Cookies文件存在，包含 {len(cookies)} 个cookie")
                return True
            else:
                print_result(False, "Cookies文件格式错误")
                return False
        except:
            print_result(False, "Cookies文件无法读取")
            return False
    else:
        print_result(False, "Cookies文件不存在 (可选，使用直连)")
        return True  # 不是必需项

def main():
    """主函数"""
    print("\n" + "=" * 70)
    print("  🔍 NGA_Scrapy 云服务器配置测试")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    tests = [
        ("Python版本", test_python_version),
        ("虚拟环境", test_virtual_env),
        ("依赖包", test_dependencies),
        ("Playwright浏览器", test_playwright_browser),
        ("数据库", test_database),
        ("代理配置", test_proxy_config),
        ("系统资源", test_system_resources),
        ("Cookies文件", test_cookies),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ 测试 '{name}' 时发生错误: {str(e)}")
            results.append((name, False))

    # 输出总结
    print_header("测试总结")
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status}: {name}")

    print(f"\n通过率: {passed}/{total} ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n🎉 所有测试通过！可以安全运行爬虫。")
        print("\n启动命令:")
        print("  bash run_cloud.sh")
        print("或")
        print("  scrapy crawl nga -s SETTINGS_MODULE=settings_cloud")
    else:
        print("\n⚠️  有测试失败，请先解决上述问题后再运行爬虫。")
        print("\n常见解决方案:")
        print("  1. 安装依赖: pip install -r requirements.txt")
        print("  2. 安装浏览器: playwright install chromium")
        print("  3. 初始化数据库: python init_db.py")
        print("  4. 配置代理: 编辑 proxy_config.json")

    print("\n" + "=" * 70 + "\n")

if __name__ == '__main__':
    main()
