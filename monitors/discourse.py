# monitors/discourse.py
"""Discourse 实例监测器（可配多实例；中文 × 结构载体）。

数据路径（2026-10-13 实测：emacs-china.org）：
- 发现：/latest.json?order=created —— 1 请求，topic 列表自带 posts_count
- 取帖：/t/{id}.json?print=true —— 1 请求返回**全部楼**（无 print 只给首尾各 20）
- 回复载体：structure —— reply_to_post_number 为结构字段（游客可得，已实测）
- 跨实例防撞：thread_id / unit_id / parent_id 均带「实例名:」前缀（不同实例的编号会重叠）
"""
import logging
import re

from monitors.base import BaseMonitor

logger = logging.getLogger('monitors.discourse')

_IMG_RE = re.compile(r'<img[^>]+?src="([^"]+)"')


def norm_iso(s):
    """Discourse 时间为 ISO8601（含毫秒），统一到秒级 UTC。"""
    if not s:
        return None
    return s[:19] + 'Z'


class DiscourseMonitor(BaseMonitor):
    platform = 'discourse'

    @property
    def cfg_dc(self):
        return self.cfg['platforms']['discourse']

    def _instances(self):
        return {i['name']: i for i in self.cfg_dc['instances']}

    def discover(self):
        cfg = self.cfg_dc
        known = self.known_threads()
        added = 0
        for inst in cfg['instances']:
            if added >= cfg['max_new_per_round'] or self._used >= self.request_budget:
                break
            if self.tracking_count() >= cfg['max_tracking']:
                logger.info(f"[discourse] 追踪清单已满（{cfg['max_tracking']}），本轮只刷新")
                break
            try:
                data = self.fetch_json(f"{inst['base_url']}/latest.json", params={'order': 'created'})
            except Exception:
                self.stats['errors'] += 1
                logger.exception(f"[discourse] 实例 {inst['name']} 发现失败")
                continue
            for t in data.get('topic_list', {}).get('topics', []):
                if added >= cfg['max_new_per_round'] or self._used >= self.request_budget:
                    break
                if (t.get('posts_count') or 0) < inst.get('min_posts', 20):
                    continue
                tid = f"{inst['name']}:{t['id']}"
                if tid in known:
                    continue
                logger.info(f"[discourse] 新追踪帖 {tid}（{t.get('posts_count')} 楼）：{(t.get('title') or '')[:60]}")
                self.add_thread(tid, inst['name'], t.get('title'), t.get('posts_count'),
                                norm_iso(t.get('last_posted_at')))
                self.refresh_thread({'thread_id': tid, 'title': t.get('title')})
                added += 1

    def refresh_thread(self, th):
        name, topic_id = th['thread_id'].split(':', 1)
        inst = self._instances()[name]
        data = self.fetch_json(f"{inst['base_url']}/t/{topic_id}.json", params={'print': 'true'})
        title = data.get('title') or th.get('title')
        posts = data.get('post_stream', {}).get('posts', [])
        num2id = {p['post_number']: p['id'] for p in posts}
        rows = []
        for p in posts:
            rtp = p.get('reply_to_post_number')
            parent = num2id.get(rtp) if rtp else None
            cooked = p.get('cooked') or ''
            imgs = _IMG_RE.findall(cooked) or None
            rows.append({
                'platform': 'discourse',
                'unit_id': f"{name}:{p['id']}",
                'community': name,
                'thread_id': th['thread_id'],
                'thread_title': title,
                'parent_id': f"{name}:{parent}" if parent else None,
                'parent_carrier': 'structure' if parent else 'none',
                'author': p.get('username'),
                'post_time': norm_iso(p.get('created_at')),
                'content': cooked,
                'content_format': 'html',
                'recommend': p.get('like_count'),
                'image_urls': imgs,
                'source_url': f"{inst['base_url']}/t/{topic_id}/{p['post_number']}",
            })
        n = self.upsert_units(rows)
        last_activity = max((r['post_time'] for r in rows if r.get('post_time')), default=None)
        self.touch_thread(th['thread_id'], len(rows), last_activity)
        return n
