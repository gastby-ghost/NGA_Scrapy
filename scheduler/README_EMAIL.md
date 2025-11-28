# 邮件通知功能使用示例

本文档提供了邮件通知功能的详细使用示例和故障排除指南。

## 目录
- [快速开始](#快速开始)
- [Gmail 配置示例](#gmail-配置示例)
- [163 邮箱配置示例](#163-邮箱配置示例)
- [QQ 邮箱配置示例](#qq-邮箱配置示例)
- [故障排除](#故障排除)
- [测试邮件发送](#测试邮件发送)

## 快速开始

### 1. 安装依赖

```bash
pip install PyYAML>=6.0
```

### 2. 配置邮件参数

编辑 `scheduler/email_config.yaml` 文件：

```yaml
smtp_server: "你的SMTP服务器"
smtp_port: 587
username: "你的邮箱地址"
password: "你的密码或应用专用密码"
from_email: "发件人邮箱"
to_emails:
  - "收件人1@example.com"
  - "收件人2@example.com"
use_tls: true

notifications:
  enable_statistics_report: true
  statistics_report_interval_days: 3
  statistics_report_time: "09:00"

  enable_error_alerts: true
  consecutive_failures_threshold: 3
  spider_timeout_minutes: 60

  error_rate_alert:
    enabled: true
    threshold_percent: 20
    time_window_minutes: 30
```

### 3. 启动调度器

```bash
cd scheduler
python run_scheduler.py
```

## Gmail 配置示例

Gmail 需要使用应用专用密码，不能使用普通密码。

### 步骤 1：开启两步验证
1. 访问 [Google 账户设置](https://myaccount.google.com/)
2. 进入"安全性" → "两步验证"，按照提示开启

### 步骤 2：生成应用专用密码
1. 在 [Google 账户设置](https://myaccount.google.com/) 中
2. 进入"安全性" → "应用专用密码"
3. 选择"邮件"和"其他（自定义名称）"
4. 输入名称，如"NGA爬虫"
5. 复制生成的 16 位密码（格式：xxxx xxxx xxxx xxxx）

### 步骤 3：配置 email_config.yaml

```yaml
smtp_server: "smtp.gmail.com"
smtp_port: 587
username: "your_email@gmail.com"
password: "abcd efgh ijkl mnop"  # 粘贴应用专用密码（包含空格）
from_email: "your_email@gmail.com"
to_emails:
  - "your_email@gmail.com"
use_tls: true

notifications:
  enable_statistics_report: true
  statistics_report_interval_days: 3
  statistics_report_time: "09:00"
  enable_error_alerts: true
  consecutive_failures_threshold: 3
  spider_timeout_minutes: 60
  error_rate_alert:
    enabled: true
    threshold_percent: 20
    time_window_minutes: 30
```

⚠️ **注意**：密码中可能包含空格，复制时保持原样，不要删除空格。

## 163 邮箱配置示例

### 步骤 1：开启 SMTP 服务
1. 登录 163 邮箱
2. 进入"设置" → "POP3/SMTP/IMAP"
3. 勾选"开启 SMTP 服务"
4. 设置客户端授权密码（不是登录密码！）

### 步骤 2：配置 email_config.yaml

```yaml
smtp_server: "smtp.163.com"
smtp_port: 587
username: "your_email@163.com"
password: "your_auth_password"  # 客户端授权密码
from_email: "your_email@163.com"
to_emails:
  - "your_email@163.com"
use_tls: true

notifications:
  enable_statistics_report: true
  statistics_report_interval_days: 3
  statistics_report_time: "09:00"
  enable_error_alerts: true
  consecutive_failures_threshold: 3
  spider_timeout_minutes: 60
  error_rate_alert:
    enabled: true
    threshold_percent: 20
    time_window_minutes: 30
```

## QQ 邮箱配置示例

### 步骤 1：开启 SMTP 服务
1. 登录 QQ 邮箱
2. 进入"设置" → "账户"
3. 找到"POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务"
4. 开启"IMAP/SMTP 服务"，获取授权码

### 步骤 2：配置 email_config.yaml

```yaml
smtp_server: "smtp.qq.com"
smtp_port: 587
username: "your_email@qq.com"
password: "your_auth_code"  # 授权码，不是 QQ 密码
from_email: "your_email@qq.com"
to_emails:
  - "your_email@qq.com"
use_tls: true

notifications:
  enable_statistics_report: true
  statistics_report_interval_days: 3
  statistics_report_time: "09:00"
  enable_error_alerts: true
  consecutive_failures_threshold: 3
  spider_timeout_minutes: 60
  error_rate_alert:
    enabled: true
    threshold_percent: 20
    time_window_minutes: 30
```

## 故障排除

### 问题 1：SMTP 认证失败

**错误信息**：
```
SMTP Authentication Error: Username and Password not accepted
```

**解决方案**：
1. **Gmail**：检查是否使用了应用专用密码，而不是普通密码
2. **163/QQ**：检查是否使用了客户端授权密码，而不是登录密码
3. 确认用户名和密码没有多余的空格
4. 确认邮箱已开启 SMTP 服务

### 问题 2：连接超时

**错误信息**：
```
SMTP Connect Error: Connection timeout
```

**解决方案**：
1. 检查网络连接
2. 确认防火墙允许出站连接
3. 尝试不同的端口（587、465、25）
4. 确认 SMTP 服务器地址正确

### 问题 3：端口 587 无法连接

**解决方案**：
尝试使用 SSL 端口 465：

```yaml
smtp_server: "smtp.gmail.com"
smtp_port: 465
use_tls: false  # SSL 端口不使用 TLS
```

### 问题 4：邮件发送频率过高被限制

**解决方案**：
1. 增加错误告警的阈值
2. 调整连续失败次数阈值
3. 错开多个服务的发送时间

### 问题 5：收不到邮件

**解决方案**：
1. 检查垃圾邮件文件夹
2. 确认收件人邮箱地址正确
3. 测试发送简单邮件验证配置

## 测试邮件发送

创建一个测试脚本 `test_email.py`：

```python
from email_notifier import EmailNotifier

# 配置邮件发送器
notifier = EmailNotifier(
    smtp_server="你的SMTP服务器",
    smtp_port=587,
    username="你的邮箱",
    password="你的密码",
    from_email="发件人邮箱",
    to_emails=["收件人邮箱"],
    use_tls=True
)

# 发送测试邮件
success = notifier.send_email(
    subject="NGA爬虫 - 测试邮件",
    body="这是一封测试邮件，用于验证邮件配置是否正确。\n\n如果收到此邮件，说明邮件功能正常工作。"
)

if success:
    print("测试邮件发送成功！")
else:
    print("测试邮件发送失败，请检查配置。")
```

运行测试：

```bash
python test_email.py
```

## 常见问题解答（FAQ）

### Q: 如何自定义统计报告的内容？
A: 修改 `email_notifier.py` 中的 `send_statistics_report` 方法，添加或删除需要的统计项。

### Q: 可以添加附件吗？
A: 可以，在 `send_email` 方法中传递 `attachments` 参数即可。

### Q: 如何临时关闭邮件通知？
A: 设置 `enable_statistics_report: false` 和 `enable_error_alerts: false`。

### Q: 可以使用企业邮箱吗？
A: 可以，只需要修改 SMTP 服务器配置为企业邮箱的服务器即可。

### Q: 如何监控邮件发送状态？
A: 查看 `scheduler.log` 文件，所有邮件发送都会记录日志。

---

更多帮助请提交 Issue 或联系项目维护者。
