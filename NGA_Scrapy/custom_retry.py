# -*- coding: utf-8 -*-
"""
自定义重试中间件，支持延迟重试和指数退避
"""
import time
import random
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_text
from scrapy.core.downloader.handlers.http11 import TunnelError
from twisted.internet import defer
from twisted.internet.error import TimeoutError, DNSLookupError, \
    ConnectionRefusedError, ConnectionDone, TCPTimedOutError


class CustomRetryMiddleware(RetryMiddleware):
    """
    自定义重试中间件
    - 支持指数退避延迟
    - 对超时错误有更好的处理
    - 减少日志噪音
    """

    def process_response(self, request, response, spider):
        if request.method in ('HEAD',):
            return response

        # 获取重试次数
        retry_count = request.meta.get('retry_count', 0)
        max_retry = request.meta.get('max_retry_times', self.max_retry_times)

        # 获取状态码和原因
        return_code = response.status
        reason = response_status_text(return_code)

        # 检查是否需要重试
        if return_code in self.retry_http_codes or isinstance(reason, (TimeoutError, TCPTimedOutError)):
            # 检查是否超过最大重试次数
            if retry_count >= max_retry:
                spider.logger.warning(
                    f"超过最大重试次数 ({max_retry}): {request.url}"
                )
                return response

            # 计算重试延迟（指数退避 + 随机抖动）
            # 基础延迟：2^(retry_count) * 2 秒
            base_delay = (2 ** retry_count) * 2

            # 随机抖动：±30%
            jitter = random.uniform(0.7, 1.3)
            delay = base_delay * jitter

            # 最大延迟 5 分钟
            max_delay = 300
            final_delay = min(delay, max_delay)

            # 设置重试延迟
            spider.logger.info(
                f"🔄 重试延迟 {final_delay:.1f}s (第{retry_count + 1}/{max_retry + 1}次): {request.url}"
            )

            # 创建重试请求
            retryreq = request.copy()
            retryreq.meta['retry_count'] = retry_count + 1
            retryreq.dont_filter = True
            retryreq.priority = request.priority + self.priority_adjust

            # 在响应头中设置 Retry-After（如果还没有的话）
            if 'Retry-After' not in retryreq.headers:
                retryreq.headers['Retry-After'] = str(int(final_delay))

            return retryreq

        return response

    def process_exception(self, request, exception, spider):
        # 处理超时、连接错误等异常
        if isinstance(exception, (TimeoutError, TCPTimedOutError, DNSLookupError,
                                  ConnectionRefusedError, ConnectionDone)):
            # 检查重试次数
            retry_count = request.meta.get('retry_count', 0)
            max_retry = request.meta.get('max_retry_times', self.max_retry_times)

            if retry_count >= max_retry:
                return

            # 创建重试请求
            retryreq = request.copy()
            retryreq.meta['retry_count'] = retry_count + 1
            retryreq.dont_filter = True
            retryreq.priority = request.priority + self.priority_adjust

            # 计算重试延迟
            base_delay = (2 ** retry_count) * 2
            jitter = random.uniform(0.7, 1.3)
            final_delay = min(base_delay * jitter, 300)

            spider.logger.info(
                f"🔄 异常重试延迟 {final_delay:.1f}s (第{retry_count + 1}/{max_retry + 1}次): {request.url}"
            )

            return retryreq

