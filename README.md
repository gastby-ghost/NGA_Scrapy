# NGA_Scrapy

一个专门用于爬取NGA论坛数据的Scrapy爬虫项目，主要功能是自动获取NGA论坛水区的主题帖、回复内容和用户信息，并将数据存储到数据库中。

## 项目简介和功能概述

NGA_Scrapy是一个功能完善的网络爬虫项目，专门针对NGA论坛（bbs.nga.cn）设计。项目采用增量爬取策略，只获取新内容，避免重复爬取，大大提高了爬取效率。

### 主要功能

- **主题爬取**：爬取NGA论坛水区(fid=-7)前10页的主题列表
- **回复爬取**：对每个主题爬取其所有回复内容
- **用户信息爬取**：获取发帖用户的基本信息
- **增量爬取**：通过比较数据库中的最后回复时间，只爬取新内容
- **图片下载**：自动下载回复中的图片并保存到本地
- **Cookie管理**：支持登录状态下的数据爬取
- **定时调度**：支持定时自动执行爬取任务

## 技术栈和依赖

- **Scrapy**：核心爬虫框架
- **SQLAlchemy**：ORM数据库操作框架
- **Playwright**：浏览器自动化工具，用于处理JavaScript渲染的页面
- **SQLite**：默认数据库（可配置其他数据库）
- **APScheduler**：定时任务调度器
- **Selenium**：用于获取Cookie的浏览器自动化工具

### 依赖安装

```bash
pip install scrapy sqlalchemy playwright apscheduler selenium psutil
playwright install chromium
```

## 项目结构说明

```
NGA_Scrapy/
├── README.md                    # 项目说明文档
├── scrapy.cfg                   # Scrapy项目配置文件
├── get_cookies.py               # Cookie获取工具
├── init_db.py                   # 数据库初始化脚本
├── NGA_Scrapy/                  # 爬虫核心目录
│   ├── __init__.py
│   ├── items.py                 # 数据项定义
│   ├── middlewares.py           # 中间件（包含Playwright集成）
│   ├── models.py                # 数据库模型定义
│   ├── pipelines.py             # 数据处理管道
│   ├── settings.py              # 爬虫配置
│   ├── spiders/                 # 爬虫目录
│   │   ├── __init__.py
│   │   └── nga_spider.py        # NGA爬虫主程序
│   └── utils/                   # 工具模块
│       └── db_utils.py          # 数据库工具
└── scheduler/                   # 定时调度器
    ├── requirements.txt         # 调度器依赖
    └── run_scheduler.py         # 调度器主程序
```

## 安装和配置指南

### 1. 克隆项目

```bash
git clone <项目地址>
cd NGA_Scrapy
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
# 或者手动安装主要依赖
pip install scrapy sqlalchemy playwright apscheduler selenium psutil
playwright install chromium
```

### 3. 初始化数据库

```bash
python init_db.py
```

### 4. 获取Cookie（可选）

如果需要爬取需要登录才能访问的内容：

```bash
python get_cookies.py
```

此命令会打开Chrome浏览器，请在40秒内手动完成NGA论坛登录，程序会自动保存Cookie到`cookies.txt`文件。

## 使用方法和运行步骤

### 1. 基本爬取

```bash
scrapy crawl nga
```

### 2. 指定数据库URL

```bash
scrapy crawl nga -a db_url="sqlite:///custom_nga.db"
```

### 3. 启动定时调度器

```bash
cd scheduler
python run_scheduler.py
```

默认每30分钟执行一次爬取任务。

## 配置说明

### 主要配置项（NGA_Scrapy/settings.py）

- `PLAYWRIGHT_POOL_SIZE`：浏览器实例池大小（默认6）
- `DOWNLOAD_TIMEOUT`：全局超时时间（默认20秒）
- `IMAGES_STORE`：图片存储路径（默认`/download_images`）
- `LOG_LEVEL`：日志级别（默认INFO）
- `LOG_FILE`：日志文件路径（默认`nga_spider.log`）

### 数据库配置

默认使用SQLite数据库，数据库文件为`nga.db`。如需使用其他数据库，可通过`db_url`参数指定，例如：

```bash
# MySQL
scrapy crawl nga -a db_url="mysql://user:password@localhost/nga_db"

# PostgreSQL
scrapy crawl nga -a db_url="postgresql://user:password@localhost/nga_db"
```

## 项目特点和亮点

### 1. 增量爬取策略
- 通过比较网页时间与数据库时间，只爬取新内容
- 避免重复爬取，提高效率
- 支持多种NGA时间格式解析

### 2. 高性能设计
- 主题列表页并行爬取（10页并发）
- 回复分页自动处理
- 数据库查询结果缓存
- 浏览器实例池管理

### 3. 完善的错误处理
- 全面的异常捕获和处理
- 详细的日志记录
- 自动重试机制

### 4. 资源管理
- 自动管理数据库连接生命周期
- 浏览器实例池复用
- 内存和CPU使用监控

### 5. 数据完整性
- 图片自动下载和本地存储
- 用户信息关联
- 主题和回复的完整关联

## 使用场景

1. **论坛数据分析**：对NGA论坛水区的内容进行数据分析
2. **舆情监控**：监控特定话题的讨论情况
3. **内容备份**：备份有价值的论坛内容
4. **用户行为研究**：研究用户发帖和回复行为
5. **趋势分析**：分析热门话题和讨论趋势

## 贡献指南

欢迎提交Issue和Pull Request来改进项目。

### 开发环境设置

1. Fork本项目
2. 创建特性分支：`git checkout -b feature/AmazingFeature`
3. 提交更改：`git commit -m 'Add some AmazingFeature'`
4. 推送到分支：`git push origin feature/AmazingFeature`
5. 提交Pull Request

## 许可证

本项目采用MIT许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 常见问题

### Q: 爬虫运行很慢怎么办？
A: 可以调整`PLAYWRIGHT_POOL_SIZE`和`CONCURRENT_REQUESTS`参数来提高并发数，但请注意不要设置过高以免对目标网站造成压力。

### Q: 如何修改爬取的页面数量？
A: 修改`NGA_Scrapy/spiders/nga_spider.py`文件中的`pageNum`变量。

### Q: 如何添加其他分区的爬取？
A: 修改`start_urls`和`parse`方法中的URL参数，将`fid=-7`改为目标分区的fid。

### Q: 数据库文件过大怎么办？
A: 可以定期清理旧数据，或者使用其他数据库系统如MySQL、PostgreSQL等。

## 更新日志

### v1.0.0
- 初始版本发布
- 实现基本爬取功能
- 支持增量爬取
- 添加图片下载功能
- 实现定时调度

---

如有问题或建议，请提交Issue或联系项目维护者。