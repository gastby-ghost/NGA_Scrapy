# get_cookies.py
"""
NGA论坛Cookie获取工具

功能：
  1. 使用Selenium打开Chrome浏览器访问NGA水区
  2. 等待用户手动登录(40秒时间窗口)
  3. 获取登录后的cookies并保存到cookies.txt文件
  4. 关闭浏览器

改进：
  - 添加弹窗处理功能
  - 增加异常处理
  - 优化文件写入方式
"""

import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import UnexpectedAlertPresentException

# 配置Chrome选项，使用Chromium
chrome_options = Options()
# chrome_options.add_argument('--headless')  # 如需无头模式，请取消注释此行
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--disable-gpu')
chrome_options.add_argument('--disable-extensions')  # 禁用扩展

# 初始化Chrome浏览器驱动
driver = webdriver.Chrome(options=chrome_options)

try:
    # 访问NGA水区页面(fid=-7)
    driver.get("https://bbs.nga.cn/thread.php?fid=-7")

    # 等待40秒让用户手动完成登录
    print("请在浏览器中完成NGA论坛登录(40秒超时)")
    time.sleep(40)

    # 处理可能的登录成功弹窗
    try:
        alert = driver.switch_to.alert
        alert.accept()  # 点击确认按钮
        time.sleep(1)  # 等待弹窗关闭
    except:
        pass  # 没有弹窗则继续

    # 获取当前所有cookies并保存为JSON格式
    cookies = driver.get_cookies()
    
    # 使用更安全的文件写入方式
    with open('cookies.txt', 'w', encoding='utf-8') as cookiefile:
        json.dump(cookies, cookiefile, ensure_ascii=False, indent=2)
    
    print("Cookies已成功保存到cookies.txt")

except UnexpectedAlertPresentException:
    print("检测到未处理的弹窗，请确保登录流程正常完成")
except Exception as e:
    print(f"发生错误: {str(e)}")
finally:
    # 确保浏览器总是会被关闭
    driver.quit()
