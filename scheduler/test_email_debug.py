#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮件配置测试脚本 - 增强版
用于测试QQ邮箱SMTP配置是否正确，提供更详细的错误信息

使用方法：
1. 修改email_config.yaml中的邮箱和授权码
2. 运行此脚本：python test_email_debug.py
"""

import yaml
import sys
import socket
from datetime import datetime


def load_email_config():
    """加载邮件配置文件"""
    import os

    # 获取脚本所在目录的绝对路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'email_config.yaml')

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        print(f"❌ 错误：找不到配置文件 {config_path}")
        print("请确保 email_config.yaml 文件与脚本位于同一目录下")
        return None
    except Exception as e:
        print(f"❌ 错误：读取配置文件失败 - {e}")
        return None


def test_smtp_connection(config):
    """测试SMTP连接"""
    smtp_server = config['smtp_server']
    smtp_port = config['smtp_port']

    print(f"\n正在测试SMTP连接: {smtp_server}:{smtp_port}...")

    try:
        # 创建socket连接
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)  # 10秒超时

        # 尝试连接
        result = sock.connect_ex((smtp_server, smtp_port))

        if result == 0:
            print(f"✅ 成功连接到 {smtp_server}:{smtp_port}")
            sock.close()
            return True
        else:
            print(f"❌ 无法连接到 {smtp_server}:{smtp_port}")
            print(f"   错误代码: {result}")
            print(f"   可能的原因:")
            print(f"   - 网络连接问题")
            print(f"   - 防火墙阻止了出站连接")
            print(f"   - 端口 {smtp_port} 被阻止")
            sock.close()
            return False

    except socket.gaierror as e:
        print(f"❌ DNS解析失败: {e}")
        print(f"   请检查SMTP服务器地址是否正确: {smtp_server}")
        return False
    except Exception as e:
        print(f"❌ 连接测试失败: {e}")
        return False


def test_email_with_debug(config):
    """使用调试模式测试邮件"""
    try:
        import smtplib
        from email.mime.text import MIMEText

        print("\n正在尝试SMTP认证和邮件发送...")

        # 创建邮件
        msg = MIMEText(f"""这是一封测试邮件，用于验证QQ邮箱SMTP配置是否正确。

测试时间：{datetime.now()}

如果收到这封邮件，说明邮件功能正常工作。

---
此邮件由NGA爬虫调度器测试脚本自动发送
""", 'plain', 'utf-8')
        msg['Subject'] = "NGA爬虫邮件通知测试"
        msg['From'] = config['from_email']
        msg['To'] = ', '.join(config['to_emails'])

        # 连接到SMTP服务器
        print(f"连接到 {config['smtp_server']}:{config['smtp_port']}...")
        if config.get('use_tls', True):
            # 使用TLS
            print("使用TLS加密...")
            server = smtplib.SMTP(config['smtp_server'], config['smtp_port'])
            server.starttls()
        else:
            # 使用SSL
            print("使用SSL加密...")
            server = smtplib.SMTP_SSL(config['smtp_server'], config['smtp_port'])

        # 登录并发送
        print("正在登录...")
        server.login(config['username'], config['password'])
        print("✅ 登录成功")

        print("正在发送邮件...")
        server.send_message(msg)
        print("✅ 邮件发送成功")

        server.quit()
        return True

    except smtplib.SMTPResponseException as e:
        print(f"❌ SMTP错误: {e}")
        print(f"   错误代码: {e.smtp_code}")
        print(f"   错误信息: {e.smtp_error}")
        print("\n常见解决方案:")
        print("1. 检查授权码是否正确（不是QQ密码）")
        print("2. 确认已开启IMAP/SMTP服务")
        print("3. 尝试使用SSL端口465（设置use_tls: false）")
        return False
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ 认证失败: {e}")
        print("可能的原因:")
        print("- 授权码不正确")
        print("- 用户名格式错误（应该是完整的邮箱地址）")
        print("- SMTP服务未开启")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"❌ 连接失败: {e}")
        print("解决方案:")
        print("1. 检查网络连接")
        print("2. 检查防火墙设置")
        print("3. 尝试使用SSL端口465")
        return False
    except Exception as e:
        print(f"❌ 未知错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def show_troubleshooting_guide():
    """显示故障排除指南"""
    print("\n" + "=" * 60)
    print("故障排除指南")
    print("=" * 60)
    print("""
如果仍然无法发送邮件，请按以下步骤排查：

1. 检查QQ邮箱设置
   - 登录QQ邮箱 → 设置 → 账户
   - 确认已开启"IMAP/SMTP服务"
   - 如果没有开启，请生成授权码

2. 检查网络连接
   - 确认服务器能访问外网
   - 检查防火墙是否阻止SMTP端口（587/465）

3. 尝试不同端口
   - 587端口失败 → 尝试465端口（SSL）
   - 编辑 email_config.yaml:
     * smtp_port: 465
     * use_tls: false

4. 检查授权码
   - 授权码不是QQ密码！
   - 授权码在邮箱设置中生成
   - 授权码可能包含空格，复制时保持原样

5. 测试网络连通性
   - 运行: telnet smtp.qq.com 587
   - 如果连接失败，说明网络或防火墙有问题

6. 检查邮箱安全设置
   - 某些邮箱可能需要开启"允许客户端授权"
   - 或者需要确认手机号码等信息

如果所有方法都无效，可能是：
- 公司网络限制（内网无法访问外网SMTP）
- 邮箱服务商限制（如需要特殊权限）
- 其他安全策略限制
""")


def main():
    print("\n" + "=" * 60)
    print("NGA爬虫 - QQ邮箱配置测试工具（增强版）")
    print("=" * 60 + "\n")

    # 加载配置
    config = load_email_config()
    if not config:
        sys.exit(1)

    # 显示配置信息
    print("当前配置:")
    print(f"   SMTP服务器：{config['smtp_server']}:{config['smtp_port']}")
    print(f"   发件人：{config['from_email']}")
    print(f"   收件人：{', '.join(config['to_emails'])}")
    print(f"   TLS加密：{'开启' if config.get('use_tls', True) else '关闭'}")

    # 测试SMTP连接
    if not test_smtp_connection(config):
        show_troubleshooting_guide()
        sys.exit(1)

    # 测试邮件发送
    if test_email_with_debug(config):
        print("\n" + "=" * 60)
        print("🎉 测试完成！邮件功能配置正确")
        print("=" * 60)
        print("\n下一步：")
        print("1. 运行调度器：python run_scheduler.py")
        print("2. 查看日志：tail -f scheduler.log")
        sys.exit(0)
    else:
        show_troubleshooting_guide()
        sys.exit(1)


if __name__ == '__main__':
    main()
