# monitors/hn.py
"""Hacker News 监测器（英文 × 结构载体标杆）。

数据路径（2026-10-13 实测验证）：
- 发现：Algolia search_by_date —— 1 请求，hit 自带 num_comments / points，不必逐帖探查
- 取帖：Algolia items/{id} —— 1 请求返回**完整嵌套评论树**（hn.algolia.com 为官方认可检索服务；
  索引有几分钟级延迟，对 30 分钟粒度的监测无碍）
- 回复载体：structure —— 评论的 parent_id 是结构字段，正文无引用痕迹。
  与 NGA 的 content 载体（正文 [pid=] 引用头）构成跨平台检验的核心对照。
"""
import logging
import time
from datetime import datetime, timezone

from monitors.base import BaseMonitor

logger = logging.getLogger('monitors.hn')

API = 'https://hn.algolia.com/api/v1'
COMMUNITY = 'hackernews'


def iso_from_i(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class HackerNewsMonitor(BaseMonitor):
    platform = 'hn'

    @property
    def cfg_hn(self):
        return self.cfg['platforms']['hn']

    def discover(self):
        cfg = self.cfg_hn
        if self.tracking_count() >= cfg['max_tracking']:
            logger.info(f"[hn] 追踪清单已满（{cfg['max_tracking']}），本轮只刷新")
            return
        since = int(time.time()) - cfg['discover_lookback_hours'] * 3600
        data = self.fetch_json(f'{API}/search_by_date', params={
            'tags': 'story',
            'numericFilters': f'points>{cfg["min_points"]},created_at_i>{since}',
            'hitsPerPage': 50,
        })
        known = self.known_threads()
        added = 0
        for h in data.get('hits', []):
            if added >= cfg['max_new_per_round'] or self._used >= self.request_budget:
                break
            sid = str(h.get('objectID') or '')
            if not sid or sid in known:
                continue
            if (h.get('num_comments') or 0) < cfg['min_comments']:
                continue
            logger.info(f"[hn] 新追踪帖 {sid}（{h.get('num_comments')} 评论）：{(h.get('title') or '')[:60]}")
            self.add_thread(sid, COMMUNITY, h.get('title'), h.get('num_comments'),
                            iso_from_i(h.get('created_at_i')))
            self.refresh_thread({'thread_id': sid, 'title': h.get('title')})
            added += 1

    def refresh_thread(self, th):
        tree = self.fetch_json(f'{API}/items/{th["thread_id"]}')
        story_id = str(tree.get('id') or th['thread_id'])
        title = tree.get('title') or th.get('title')
        rows = list(self._flatten(tree, story_id=story_id, title=title))
        n = self.upsert_units(rows)
        last_activity = max((r['post_time'] for r in rows if r.get('post_time')), default=None)
        self.touch_thread(story_id, len(rows), last_activity)
        return n

    def _flatten(self, node, story_id, title):
        """Algolia items 返回嵌套 children 树——展平为统一记录行。"""
        nid = node.get('id')
        if nid is not None:
            pid = node.get('parent_id')
            yield {
                'platform': 'hn',
                'unit_id': str(nid),
                'community': COMMUNITY,
                'thread_id': story_id,
                'thread_title': title,
                'parent_id': str(pid) if pid else None,
                'parent_carrier': 'structure' if pid else 'none',
                'author': node.get('author'),
                'post_time': iso_from_i(node.get('created_at_i')),
                'content': node.get('text'),
                'content_format': 'html',
                'recommend': node.get('points'),
                'image_urls': None,
                'source_url': f'https://news.ycombinator.com/item?id={nid}',
            }
        for c in node.get('children') or []:
            yield from self._flatten(c, story_id, title)
