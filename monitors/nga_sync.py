# monitors/nga_sync.py
"""NGA reply → post 增量同步器。

reply/topic/user 是 NGA 采集器（scrapy spider）的内部形态；post 表是分析契约。
本同步器是单向桥梁：**分析层只读 post**，不直接读 reply。

同步语义：anti-join（post 表里还没有的 reply 即为增量）——幂等，且不依赖 rid 单调假设
（相比「最大 rid 水位线」更稳，也不会漏掉任何回填数据）。
parent_carrier=content：NGA 的回复关系写在正文引用头（[pid=]），由 spider 提取到 parent_rid。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from NGA_Scrapy.models import Post

logger = logging.getLogger('monitors.nga_sync')

_NGA_FORMATS = [
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
    '%y-%m-%d %H:%M:%S', '%y-%m-%d %H:%M',
    '%d-%m-%y %H:%M:%S', '%d-%m-%y %H:%M',
]


def nga_time_to_utc(s):
    """NGA 时间为北京时间（多种历史格式）；转 UTC ISO8601。解析失败保留原串（异常可见）。"""
    if not s:
        return None
    for fmt in _NGA_FORMATS:
        try:
            dt = datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone(timedelta(hours=8)))
            return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            continue
    logger.warning('NGA 时间解析失败，保留原串: %r', s)
    return s


def sync_nga(engine, batch=5000):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT r.rid, r.tid, r.parent_rid, r.content, r.recommendvalue, r.poster_id,
                   r.post_time, r.image_urls, r.sampling_time, t.title, t.partition
            FROM reply r
            LEFT JOIN topic t ON r.tid = t.tid
            LEFT JOIN post p ON p.platform = 'nga' AND p.unit_id = r.rid
            WHERE p.unit_id IS NULL
            LIMIT :lim
        """), {'lim': batch}).mappings().all()
    if not rows:
        return 0
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    payload = [{
        'platform': 'nga',
        'unit_id': r['rid'],
        'community': r['partition'],
        'thread_id': r['tid'],
        'thread_title': r['title'],
        'parent_id': r['parent_rid'] or None,
        'parent_carrier': 'content' if r['parent_rid'] else 'none',
        'author': r['poster_id'],
        'post_time': nga_time_to_utc(r['post_time']),
        'content': r['content'],
        'content_format': 'ubb',
        'recommend': r['recommendvalue'],
        'image_urls': r['image_urls'],
        'source_url': f"https://bbs.nga.cn/read.php?tid={r['tid']}&pid={r['rid']}",
        'sampled_at': r['sampling_time'],
        'last_seen': now,
    } for r in rows]
    with engine.begin() as conn:
        stmt = pg_insert(Post.__table__).values(payload)
        conn.execute(stmt.on_conflict_do_nothing(index_elements=['platform', 'unit_id']))
    logger.info('[nga_sync] 同步 %d 楼（reply → post）', len(payload))
    return len(payload)
