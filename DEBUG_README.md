# NGA爬虫调试功能使用说明

## 📋 新增的调试功能

### 1. HTML页面自动保存

当遇到以下情况时，系统会自动保存HTML文件到 `debug_html/` 目录：

- **页面内容过短** (< 1000字符)
- **检测到反爬虫提示** (验证码、IP被封等)
- **未找到主题** (解析结果为0)
- **页面不是NGA内容**
- **响应内容异常**

### 2. 详细调试日志

#### middlewares.py 新增日志：
```python
# 页面加载时
🔍 [DEBUG] 页面内容长度: XXXX 字符
⚠️ [DEBUG] 页面内容过短 (XXXX 字符)，可能未正常加载
⚠️ [DEBUG] 检测到反爬虫或验证页面

# 页面获取成功时
✅ [页面获取成功] URL... (X.XXs)
  🔍 [DEBUG] 内容长度: XXXX 字符
```

#### nga_spider.py 新增日志：
```python
# 解析开始时
📝 开始解析第 X 页主题列表 (URL: ...)
🔍 [DEBUG] 页面内容长度: XXXX 字符

# 解析结果异常时
⚠️ 第 X 页没有收集到有效主题
⚠️ [DEBUG] 详细分析:
  - 原始rows数量: X
  - 页面内容长度: XXXX
  - URL: ...
  - 页面标题: ...
  - 包含'row' class的元素数量: X
  - 所有tr元素数量: X
  - 总链接数: X, NGA相关链接数: X
```

### 3. 页面结构分析

当没有找到主题时，系统会自动分析页面结构：

- ✅ 检查页面标题
- ✅ 查找错误信息 (404、页面不存在、访问被拒绝等)
- ✅ 统计各种DOM元素数量
- ✅ 分析链接数量
- ✅ 检查是否包含预期的HTML结构

## 📁 文件命名规则

HTML调试文件命名格式：
```
{时间戳}_page{页码}_{URL哈希}_{原因}.html
```

例如：
```
20251207_143052_page1_1234_no_topics_found.html
20251207_143053_page2_5678_anti_bot_detected.html
```

## 🔍 调试原因标签

| 标签 | 说明 |
|------|------|
| `content_too_short` | 页面内容过短 |
| `no_nga_content` | 页面不是NGA内容 |
| `anti_bot` | 检测到反爬虫提示 |
| `not_nga_content` | 响应不是NGA内容 |
| `anti_bot_detected` | 检测到反爬虫 |
| `no_topics_found` | 未找到主题 |
| `response_too_short` | 响应内容过短 |

## 🛠️ 使用方法

### 1. 运行爬虫
```bash
scrapy crawl nga
```

### 2. 查看日志
```bash
tail -f nga_spider.log | grep -E "DEBUG|DEBUG"
```

### 3. 检查调试文件
```bash
ls -la debug_html/
```

### 4. 在浏览器中打开HTML文件
```bash
# 查看最新的调试文件
ls -t debug_html/*.html | head -1 | xargs firefox
```

## 🎯 常见问题诊断

### 问题1：解析到0个主题

**日志表现：**
```
⚠️ 第 1 页没有收集到有效主题
⚠️ [DEBUG] 详细分析:
  - 原始rows数量: 0
  - 页面内容长度: 1234
```

**可能原因：**
1. 页面未正常加载 → 检查 `debug_html/*_content_too_short.html`
2. 被反爬虫拦截 → 检查 `debug_html/*_anti_bot_detected.html`
3. XPath选择器失效 → 检查HTML文件中的DOM结构
4. IP被封 → 检查页面内容

### 问题2：页面内容异常

**日志表现：**
```
⚠️ [DEBUG] 页面内容过短 (123 字符)，可能未正常加载
💾 [DEBUG] HTML已保存: debug_html/20251207_143052_1234_content_too_short.html
```

**处理方法：**
1. 查看保存的HTML文件
2. 检查是否是登录页面、验证页面或错误页面
3. 检查代理配置

### 问题3：反爬虫检测

**日志表现：**
```
⚠️ [DEBUG] 检测到反爬虫或验证页面
❌ [DEBUG] 检测到反爬虫提示: ['验证码', '访问过于频繁']
```

**处理方法：**
1. 检查代理是否正常工作
2. 增加请求延迟
3. 更换代理IP
4. 检查User-Agent等浏览器指纹

## 📊 调试流程

1. **观察日志** → 找到异常信息和保存的HTML文件
2. **查看HTML** → 在浏览器中打开HTML文件分析
3. **检查原因** → 根据日志标签确定问题类型
4. **解决问题** → 根据分析结果调整配置或代码

## 💡 最佳实践

1. **定期清理调试文件**：
   ```bash
   # 删除7天前的调试文件
   find debug_html/ -name "*.html" -mtime +7 -delete
   ```

2. **设置调试文件上限**：
   ```bash
   # 保留最新的100个调试文件
   ls -t debug_html/*.html | tail -n +101 | xargs rm -f
   ```

3. **批量分析调试文件**：
   ```bash
   # 统计各种问题的数量
   grep -r "Reason:" debug_html/ | cut -d: -f4 | sort | uniq -c
   ```

## 🔧 扩展功能

如果需要添加新的调试条件，可以修改以下文件：

- **middlewares.py**: `PageFetcher.fetch()` 方法
- **nga_spider.py**: `parse_topic_list()` 和 `_analyze_page_structure()` 方法

在相应位置添加检查逻辑和HTML保存调用即可。
