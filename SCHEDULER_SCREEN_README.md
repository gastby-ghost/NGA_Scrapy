# NGA爬虫调度器 - Screen后台运行模式

## 功能特点

- 使用`screen`在后台运行调度器，不受SSH断开影响
- 完整的会话管理功能（查看状态、重新连接、停止、重启）
- 自动检查环境、数据库连接和配置文件
- 实时日志查看功能
- 优雅退出支持（Ctrl+\）

## 使用方法

```bash
# 1. 基本操作
bash run_scheduler.sh start    # 启动调度器
bash run_scheduler.sh status   # 查看运行状态
bash run_scheduler.sh attach   # 连接到会话
bash run_scheduler.sh stop     # 停止调度器
bash run_scheduler.sh restart  # 重启调度器
bash run_scheduler.sh logs     # 查看实时日志

# 2. 快捷方式（start可省略）
bash run_scheduler.sh          # 默认为start命令

# 3. 查看screen会话列表
screen -list

# 4. 从screen会话中分离（保持运行）
# 在screen会话中按: Ctrl+A 然后按 D

# 5. 优雅退出
# 在screen会话中按: Ctrl+\\

# 6. 查看历史日志（在screen会话外）
tail -f scheduler/scheduler.log
```

## 启动流程

```bash
🚀 NGA爬虫调度器 - Screen后台运行模式
=========================================

📋 检查环境...
✅ screen已安装
✅ 虚拟环境已存在
✅ 调度器脚本已存在
✅ 邮件配置已存在
🔍 检查PostgreSQL服务...
✅ PostgreSQL服务正在运行
🗄️  检查数据库连接...
✅ PostgreSQL连接成功
📊 检查数据表...
✅ 所有数据表已存在 (3/3)
   user: 150 条记录
   topic: 892 条记录
   reply: 4563 条记录

🚀 启动调度器...
📄 已清空旧日志
✅ 调度器启动成功

📊 状态信息:
  Screen会话: nga_scheduler
  日志文件: scheduler/scheduler.log

📋 管理命令:
  查看状态: bash run_scheduler.sh status
  重新连接: bash run_scheduler.sh attach
  停止: bash run_scheduler.sh stop
  查看日志: bash run_scheduler.sh logs

⏳ 等待10秒后查看初始日志...

📄 最近日志:
=========================================
NGA 爬虫调度器启动
=========================================
配置信息:
  - 时区: Asia/Shanghai
  - 执行间隔: 30 分钟
  - 启动时间: 2025-01-15 09:23:45
  - 日志文件: scheduler.log
  - 邮件通知: 已启用
  - 统计报告: 启用
  - 首次统计报告: 将在第一次爬虫成功后发送
  - 错误告警: 启用
=========================================
```

## 状态查看

```bash
$ bash run_scheduler.sh status

✅ 调度器正在运行
12345.nga_scheduler       (02/15/2025 09:23:45 AM)        (Detached)

📄 日志文件大小: 45K

📋 最近日志:
2025-01-15 09:23:45 - scheduler - INFO - NGA 爬虫调度器启动
2025-01-15 09:23:45 - scheduler - INFO - 配置信息:
2025-01-15 09:24:15 - scheduler - INFO - 开始执行爬虫任务 - 2025-01-15 09:24:15
2025-01-15 09:24:15 - scheduler - INFO - ==============

📊 统计文件:
-rw-r--r-- 1 user user 12K Jan 15 09:30 spider_stats_20250115_093000.json
-rw-r--r-- 1 user user 13K Jan 15 10:00 spider_stats_20250115_100000.json
```

## Screen会话管理

### 会话分离
在screen会话内：
- 按 `Ctrl+A` 然后按 `D` - 分离会话，保持后台运行
- 按 `Ctrl+\\` - 优雅退出scheduler（推荐）

### 重新连接
```bash
# 方法1: 使用脚本
bash run_scheduler.sh attach

# 方法2: 手动连接
screen -r nga_scheduler
```

### 强制终止
如果scheduler无响应：
```bash
# 方法1: 使用脚本
bash run_scheduler.sh stop

# 方法2: 手动停止
screen -S nga_scheduler -X quit

# 方法3: 杀掉所有screen会话
tmux kill-server  # 如果使用tmux
pkill -f screen   # 强制杀死所有screen进程
```

## 日志管理

### 实时日志
```bash
# 在screen会话外查看实时日志
bash run_scheduler.sh logs

tail -f scheduler/scheduler.log  # 或使用tail
```

### 日志文件位置
- 主日志: `scheduler/scheduler.log`
- 爬虫日志: `nga_spider.log`
- 统计文件: `scheduler/stats/spider_stats_*.json`

### 日志轮转
- scheduler.log: 手动清空（每次启动时）
- nga_spider.log: 自动轮转（10MB分割，保留5个备份）

## 故障排查

### 1. 无法启动 - screen未安装
```bash
# Ubuntu/Debian
sudo apt-get install screen

# CentOS/RHEL
sudo yum install screen
```

### 2. 无法启动 - 缺少依赖
```bash
# 检查并安装依赖
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 调度器启动后立即退出
```bash
# 查看错误日志
bash run_scheduler.sh logs

# 常见原因:
# - 数据库连接失败
# - email_config.yaml配置错误
# - 缺少必要的Python包
```

### 4. Screen会话无法连接
```bash
# 查看所有screen会话
screen -list

# 如果有Attached状态的会话
screen -D -r nga_scheduler  # 强制分离并重新连接
```

### 5. 进程残留
```bash
# 检查是否有残留的scheduler进程
ps aux | grep run_scheduler.py

# 清理残留的screen进程
pkill -f "SCREEN.*nga_scheduler"
```

## 常见问题

### Q1: 如何查看调度器是否在运行？
```bash
bash run_scheduler.sh status
# 或
screen -list | grep nga_scheduler
```

### Q2: SSH断开后如何重新连接？
```bash
bash run_scheduler.sh attach
# 会自动连接到已有的session
```

### Q3: 如何优雅地停止调度器？
在主目录执行：
```bash
bash run_scheduler.sh stop
```

或在screen会话内：
- 按 `Ctrl+\\` （推荐）
- 或按 `Ctrl+C`

### Q4: 如何修改调度频率？
编辑 `scheduler/run_scheduler.py`:
```python
# 修改interval参数
scheduler.add_job(
    run_spider,
    'interval',
    minutes=30,  # 改为需要的间隔（分钟）
    id='nga_spider_job',
    ...
)
```

然后重启：
```bash
bash run_scheduler.sh restart
```

### Q5: 如何禁用邮件通知？
编辑 `scheduler/email_config.yaml`:
```yaml
notifications:
  enable_statistics_report: false
  enable_error_alerts: false
```

## 与run_postgresql.sh对比

| 特性 | run_postgresql.sh | run_scheduler.sh |
|------|-------------------|------------------|
| 运行方式 | 前台运行 | Screen后台运行 |
| SSH断开影响 | 进程终止 | 不受影响 |
| 日志查看 | 实时显示 | screen或日志文件 |
| 重新连接 | 不支持 | 支持（attach） |
| 调度功能 | 单次运行 | 定时调度 |
| 邮件通知 | ❌ | ✅ |
| 统计报告 | ❌ | ✅ |
| 错误告警 | ❌ | ✅ |

## 最佳实践

1. **首次使用**
   ```bash
   # 1. 配置邮件通知
   cp scheduler/email_config.yaml.example scheduler/email_config.yaml
   # 编辑 scheduler/email_config.yaml

   # 2. 启动调度器
   bash run_scheduler.sh start

   # 3. 查看状态确认正常
   bash run_scheduler.sh status
   ```

2. **日常使用**
   ```bash
   # 登录后查看状态
   bash run_scheduler.sh status

   # 需要调试时连接会话
   bash run_scheduler.sh attach

   # 查看日志
   bash run_scheduler.sh logs
   ```

3. **维护操作**
   ```bash
   # 重启调度器（配置修改后）
   bash run_scheduler.sh restart

   # 清理旧日志
   cat /dev/null > scheduler/scheduler.log
   cat /dev/null > nga_spider.log

   # 清理旧统计文件（保留30天）
   find scheduler/stats -name "*.json" -mtime +30 -delete
   ```

4. **监控告警**
   - 配置邮件通知后，系统会自动发送统计报告和错误告警
   - 定期检查 `scheduler/stats/` 目录的统计文件
   - 监控磁盘空间（日志和统计数据会持续增长）
