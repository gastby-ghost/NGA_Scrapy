# items.py
import scrapy

class UserItem(scrapy.Item):
    uid = scrapy.Field()
    name = scrapy.Field()
    user_group = scrapy.Field()
    prestige = scrapy.Field()
    reg_date = scrapy.Field()
    history_re_num = scrapy.Field()

class TopicItem(scrapy.Item):
    tid = scrapy.Field()
    title = scrapy.Field()
    poster_id = scrapy.Field()
    post_time = scrapy.Field()
    re_num = scrapy.Field()
    sampling_time = scrapy.Field()
    last_reply_date = scrapy.Field()
    partition=scrapy.Field()

class ReplyItem(scrapy.Item):
    rid = scrapy.Field()
    tid = scrapy.Field()
    parent_rid = scrapy.Field()
    content = scrapy.Field()
    recommendvalue = scrapy.Field()
    poster_id = scrapy.Field()
    post_time = scrapy.Field()
    sampling_time = scrapy.Field()
    image_urls = scrapy.Field()  # 新增图片URL字段
    image_paths = scrapy.Field()      # 新增图片存储信息字段
