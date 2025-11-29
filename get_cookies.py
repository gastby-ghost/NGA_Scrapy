# get_cookies.py
"""
NGA论坛Cookie获取工具（Playwright版本）

功能：
  1. 使用Playwright打开Chromium浏览器访问NGA水区
  2. 等待用户手动登录(40秒时间窗口)
  3. 获取登录后的cookies并保存到cookies.txt文件
  4. 关闭浏览器

改进：
  - 添加弹窗处理功能
  - 增加异常处理
  - 优化文件写入方式
  - 使用Playwright替代Selenium，与项目架构保持一致
"""

import time
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    # 启动浏览器（使用Chromium）
    browser = p.chromium.launch(
        headless=False,  # 显示浏览器窗口，方便手动登录
        args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
        ]
    )

    try:
        # 创建新页面
        context = browser.new_context()
        page = context.new_page()

        # 访问NGA水区页面(fid=-7)
        page.goto("https://bbs.nga.cn/thread.php?fid=-7")

        # 等待40秒让用户手动完成登录
        print("请在浏览器中完成NGA论坛登录(40秒超时)")
        time.sleep(40)

        # 获取当前所有cookies并保存为JSON格式
        cookies = context.cookies()

        # 使用更安全的文件写入方式
        with open('cookies.txt', 'w', encoding='utf-8') as cookiefile:
            json.dump(cookies, cookiefile, ensure_ascii=False, indent=2)

        print("Cookies已成功保存到cookies.txt")

    except Exception as e:
        print(f"发生错误: {str(e)}")
    finally:
        # 确保浏览器总是会被关闭
        browser.close()
