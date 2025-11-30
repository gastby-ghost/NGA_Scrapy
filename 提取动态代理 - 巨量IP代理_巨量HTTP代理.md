## 提取动态代理

##### 最新更新时间：2021.09.15[¶](https://www.juliangip.com/help/api/dynamic/#20210915 "Permanent link")

本接口主要用于提取动态代理，巨量系统会按照用户提交参数返回相应的动态HTTP代理列表，用户可在提取后根据自己的实际业务调用相关代理。

___

使用须知

在请求提取IP链接之前需在订单设置中添加进行请求的服务器IP,否则无法获取到IP信息

### 1\. 接口说明[¶](https://www.juliangip.com/help/api/dynamic/#1 "Permanent link")

-   适用对象：所有付费用户
-   请求URL：[http://v2.api.juliangip.com/dynamic/getips](http://v2.api.juliangip.com/dynamic/getips)
-   请求方式：POST/GET
-   请求频率：10次/秒

### 2\. 请求参数释义[¶](https://www.juliangip.com/help/api/dynamic/#2 "Permanent link")

| 参数名 | 变量 | 变量类型 | 是否必填 | 参数说明 |
| --- | --- | --- | --- | --- |
| 业务编号 | trade\_no | string | 是 | 由巨量系统生成的业务编号，全局唯一。  
示例值：1765244755300652 |
| 提取数量 | num | Int | 是 | 单次提取数量，目前最大单次提取数量为100。  
示例值：10 |
| 代理类型 | pt | int | 否 | 提取IP支持的代理类型  
1：HTTP代理\[默认\]  
2：SOCK代理  
示例值：`2` |
| 返回类型 | result\_type | string | 否 | 接口返回内容的格式要求  
text：文本格式\[默认\]  
json：json格式  
xml: xml格式  
示例值：`json` |
| 结果分隔符 | split | string | 否 | 提取结果列表中每个结果的分隔符  
1：\\r\\n分割 \[默认\]  
2：\\n分割  
3：空格分割  
4：|分割  
示例值：`3` |
| 地区名称 | city\_name | int | 否 | 返回的数据中携带IP归属城市名称  
不带此参数代表不过滤  
固定值：`1`  
示例：`112.84.17.21:31114,江苏徐州` |
| 邮政编码 | city\_code | int | 否 | 返回的数据中携带IP归属城市邮政编码  
不带此参数代表不过滤  
固定值：`1`  
示例：`114.98.162.2:48581,340281` |
| 剩余可用时长 | ip\_remain | int | 否 | 返回的数据中携带IP剩余可用时长（秒）  
不带此参数代表不过滤  
固定值：`1`  
示例：`114.98.162.2:48581,281` |
| 授权信息 | auth\_info | int | 否 | 返回的数据中携带账户密码  
不带此参数代表不过滤  
固定值：`1`  
示例：`12344567890:sdfwe` |
| 筛选地区 | area | string | 否 | 按照需求地区提取IP，支持多地区，用英文逗号分割  
不带此参数代表不过滤  
示例：`北京,上海,广州` |
| 运营商筛选 | isp | string | 否 | 筛选以特定运营商提供的IP  
不带此参数代表不过滤  
可选值：电信，联通，移动  
示例：`电信` |
| IP去重 | filter | int | 否 | 过滤今天提取过的IP  
不带此参数代表不过滤  
固定值：`1` |
| 加密签名 | sign | string | 是 | 由用户ID和密钥经过MD5加密后得到的签名字符串  
示例：`e10adc3949ba59abbe56e057f20f883e` |

### 3\. 调用示例[¶](https://www.juliangip.com/help/api/dynamic/#3 "Permanent link")

在会员中心[动态代理产品管理](https://www.juliangip.com/users/product/time) -> `生成提取链接`得到业务编号和API Key。

-   订单号：`1483587531995538`
-   key：`99064631962e4e838dac1143092f6112`

**参数释义** 提取10个动态代理IP，包含城市名称、邮政编号、以|分割、返回类型为xml

```
GET http://v2.api.juliangip.com/dynamic/getips?
trade_no=1483587531995538&num=10&city_name=1&city_code=1&split=3&result_type=xml
&sign=ad541361a822e64df5ef289593bef40d
```

### 4\. 返回参数释义[¶](https://www.juliangip.com/help/api/dynamic/#4 "Permanent link")

| 参数名 | 变量 | 变量类型 | 是否必返 | 参数说明 |
| --- | --- | --- | --- | --- |
| 返回码 | code | int | 是 | 返回结果状态码  
示例值：200 |
| 结果描述 | msg | string | 是 | 针对于状态码的详细描述。  
示例值：请求成功 |
| 数据内容 | data | object | 否 | 包含接口返回的数据，失败时无此参数 |
| 当前提取数量 | data.count | int | 否 | 本次提取IP总数  
如果选择去重，则为去重后的IP总数 |
| 重复IP数量 | data.filter\_count | int | 否 | 本次重复的IP数量 |
| 剩余数量 | data.surplus\_quantity | int | 否 | 订单当前剩余可提取数量 |
| 代理IP列表 | data.proxy\_list | string | 否 | 本次提取到的代理IP列表 |

#### 文本返回格式示例[¶](https://www.juliangip.com/help/api/dynamic/#_1 "Permanent link")

提取成功返回默认代理格式为`ip:port`，更多配置可参考 [请求参数释义](https://www.juliangip.com/help/api/dynamic/#2)

返回示例：

```
119.112.92.233:38727
119.116.78.232:33016
114.101.252.249:42885
101.18.85.198:51032
```

提取失败默认返回失败信息，具体错误请参照提示语

```
ERROR(401):签名校验失败，请参照开发文档修改或联系客服处理。
```

#### JSON返回格式示例[¶](https://www.juliangip.com/help/api/dynamic/#json "Permanent link")

提取成功返回示例

```
{
  "code": 200,
  "msg": "请求成功",
  "data": {
    "count": 5,
    "filter_count": 0,
    "surplus_quantity": 985,
    "proxy_list": [
      "61.145.245.78:54873",
      "27.153.143.162:35525",
      "117.69.63.120:43100",
      "150.255.11.35:55078",
      "113.195.169.143:44370"
    ]
  }
}
```

提取失败返回示例

```
{
  "code": 401,
  "msg": "签名校验失败，请参照开发文档修改或联系客服处理。",
  "data": []
}
```

#### XML格式返回示例[¶](https://www.juliangip.com/help/api/dynamic/#xml "Permanent link")

提取成功返回示例

```
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<result>
  <code>200</code>
  <msg>请求成功</msg>
  <data>
    <count>5</count>
    <filter_count>0</filter_count>
    <surplus_quantity>975</surplus_quantity>
    <proxy_list>
      <proxy>60.174.190.199:31129</proxy>
      <proxy>36.63.247.195:52355</proxy>
      <proxy>175.42.158.192:56381</proxy>
      <proxy>117.26.220.124:39276</proxy>
      <proxy>113.237.185.182:58169</proxy>
    </proxy_list>
  </data>
</result>
```

提取失败返回示例

```
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<result>
  <code>401</code>
  <msg>签名校验失败，请参照开发文档修改或联系客服处理。</msg>
  <data></data>
</result>
```

### 5\. 错误码与解决方案[¶](https://www.juliangip.com/help/api/dynamic/#5 "Permanent link")

错误提示

大部分错误都可以在【[公共错误及解决方案](https://www.juliangip.com/help/api/error/)】找到解决办法，具体错误原因请参照msg字段中的错误原因释义，我们尽可能为您提供详细的错误原因提示。

### 6\. 生成API链接[¶](https://www.juliangip.com/help/api/dynamic/#6-api "Permanent link")

您可以在线生成API链接，以便内置到您的程序或软件中。 [生成API链接](https://www.juliangip.com/users/product/time)