# monitors/base.py
"""多平台监测器公共骨架：礼貌访问（节流 + 每轮预算）、统一落库、轮次编排。

设计约束（2026-10-13 用户裁决：长期实时监测多论坛）：
- 对目标论坛尽可能低影响：请求最小间隔 + 每轮请求预算 + 声明研究身份的 UA + 只拉增量
  （每帖刷新 1 个请求：HN 走 Algolia items 全树、Discourse 走 print=true 全楼）
- 对本地省性能：纯 HTTP（无浏览器、无 scrapy），与 NGA spider 错峰调度
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from urllib3.util.retry import Retry

from NGA_Scrapy.models import Post, MonitorThread

logger = logging.getLogger('monitors')

USER_AGENT = 'academic-research-monitor/0.1 (forum reply-behavior study; low-rate polite crawler)'


class BudgetExceeded(Exception):
    """本轮请求预算用尽——提前结束本轮，下轮继续（低影响护栏）"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


class BaseMonitor:
    platform = None  # 子类覆盖：hn | discourse

    def __init__(self, config: dict, engine):
        self.cfg = config
        self.engine = engine
        pol = config['politeness']
        self.request_interval = float(pol['request_interval_sec'])
        self.request_budget = int(pol['budget_per_round'])
        self.timeout = float(pol['timeout_sec'])
        self.max_round_seconds = float(pol.get('max_round_seconds', 600))
        self._used = 0
        self._last_request = 0.0
        self._round_deadline = float('inf')
        self.stats = {'requests': 0, 'units_written': 0, 'new_threads': 0, 'refreshed': 0, 'errors': 0}

        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        retry = Retry(total=2, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    # ---------- 礼貌访问 ----------

    def fetch_json(self, url, params=None):
        if self._used >= self.request_budget or time.monotonic() > self._round_deadline:
            raise BudgetExceeded()
        wait = self.request_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        self._used += 1
        self.stats['requests'] += 1
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def budget_left(self) -> int:
        return self.request_budget - self._used

    # ---------- 落库 ----------

    def upsert_units(self, rows):
        """批量写统一记录表；同一楼重复出现时更新可变字段（幂等）。"""
        if not rows:
            return 0
        now = utcnow_iso()
        for r in rows:
            r.setdefault('sampled_at', now)
            r['last_seen'] = now
        with self.engine.begin() as conn:
            stmt = pg_insert(Post.__table__).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=['platform', 'unit_id'],
                set_={
                    'parent_id': stmt.excluded.parent_id,
                    'parent_carrier': stmt.excluded.parent_carrier,
                    'author': stmt.excluded.author,
                    'post_time': stmt.excluded.post_time,
                    'content': stmt.excluded.content,
                    'content_format': stmt.excluded.content_format,
                    'recommend': stmt.excluded.recommend,
                    'image_urls': stmt.excluded.image_urls,
                    'thread_title': stmt.excluded.thread_title,
                    'last_seen': stmt.excluded.last_seen,
                },
            )
            conn.execute(stmt)
        self.stats['units_written'] += len(rows)
        return len(rows)

    # ---------- 监测清单 ----------

    def known_threads(self) -> set:
        with self.engine.connect() as conn:
            rs = conn.execute(
                text('SELECT thread_id FROM monitor_thread WHERE platform=:p'), {'p': self.platform})
            return {r[0] for r in rs}

    def tracking_count(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM monitor_thread WHERE platform=:p AND status='tracking'"),
                {'p': self.platform}).scalar()

    def add_thread(self, thread_id, community, title, unit_count, last_activity_at):
        now = utcnow_iso()
        with self.engine.begin() as conn:
            stmt = pg_insert(MonitorThread.__table__).values(
                platform=self.platform, thread_id=str(thread_id), community=community, title=title,
                status='tracking', unit_count=unit_count, discovered_at=now,
                last_fetched_at=now, last_activity_at=last_activity_at)
            conn.execute(stmt.on_conflict_do_nothing(index_elements=['platform', 'thread_id']))
        self.stats['new_threads'] += 1

    def touch_thread(self, thread_id, unit_count, last_activity_at, status='tracking'):
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE monitor_thread
                SET unit_count=:c, last_activity_at=:a, last_fetched_at=:f, status=:s
                WHERE platform=:p AND thread_id=:t
            """), {'c': unit_count, 'a': last_activity_at, 'f': utcnow_iso(),
                   's': status, 'p': self.platform, 't': str(thread_id)})

    def active_threads(self, limit):
        """tracking 状态的帖，最久未刷新的优先（轮转刷新，防单帖霸占预算）。"""
        with self.engine.connect() as conn:
            rs = conn.execute(text("""
                SELECT thread_id, community, title, unit_count, last_fetched_at, last_activity_at
                FROM monitor_thread
                WHERE platform=:p AND status='tracking'
                ORDER BY last_fetched_at ASC NULLS FIRST
                LIMIT :n
            """), {'p': self.platform, 'n': limit})
            return [dict(r._mapping) for r in rs]

    def cool_stale_threads(self, active_hours):
        now = datetime.now(timezone.utc)
        cool_before = (now - timedelta(hours=active_hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        done_before = (now - timedelta(hours=active_hours * 7)).strftime('%Y-%m-%dT%H:%M:%SZ')
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE monitor_thread SET status='cooled'
                WHERE platform=:p AND status='tracking' AND last_activity_at < :c
            """), {'p': self.platform, 'c': cool_before})
            conn.execute(text("""
                UPDATE monitor_thread SET status='done'
                WHERE platform=:p AND status='cooled' AND last_activity_at < :d
            """), {'p': self.platform, 'd': done_before})

    # ---------- 轮次编排 ----------

    def run(self):
        t0 = time.monotonic()
        self._round_deadline = t0 + self.max_round_seconds
        logger.info(f'[{self.platform}] 监测轮开始')
        try:
            self.discover()
        except BudgetExceeded:
            logger.info(f'[{self.platform}] 发现阶段预算用尽，提前结束')
        except Exception:
            self.stats['errors'] += 1
            logger.exception(f'[{self.platform}] 发现阶段失败')
        try:
            self.refresh_tracking()
        except Exception:
            self.stats['errors'] += 1
            logger.exception(f'[{self.platform}] 刷新阶段失败')
        self.cool_stale_threads(self.cfg['platforms'][self.platform]['active_hours'])
        s = self.stats
        logger.info(f"[{self.platform}] 监测轮结束 {time.monotonic() - t0:.1f}s | "
                    f"请求 {s['requests']} | 写入 {s['units_written']} 楼 | "
                    f"新追踪 {s['new_threads']} | 刷新 {s['refreshed']} 帖 | 错误 {s['errors']}")

    def refresh_tracking(self):
        cfg = self.cfg['platforms'][self.platform]
        threads = self.active_threads(cfg['max_tracking'])
        min_gap = cfg.get('min_refresh_gap_min', 20)
        for th in threads:
            if self._used >= self.request_budget:
                logger.info(f'[{self.platform}] 预算用尽，余下追踪帖下轮继续')
                break
            lf = th.get('last_fetched_at')
            if lf and (datetime.now(timezone.utc) - parse_iso(lf)).total_seconds() / 60 < min_gap:
                continue
            try:
                self.refresh_thread(th)
                self.stats['refreshed'] += 1
            except BudgetExceeded:
                break
            except Exception:
                self.stats['errors'] += 1
                logger.exception(f"[{self.platform}] 刷新失败 {th['thread_id']}")

    # 子类实现
    def discover(self):
        raise NotImplementedError

    def refresh_thread(self, th):
        raise NotImplementedError
