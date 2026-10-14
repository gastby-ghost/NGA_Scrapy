#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填推荐值（recommendvalue）——2026-10-14

背景：`span.recommendvalue`（赞/推荐值）由 NGA 前端 JS 渲染——HTTP 快路径取服务器
原始体、domcontentloaded 即时快照，两者都拿不到该组件（此前整库 31,803 楼全零的成因）。
同一数据在原始体内联脚本 `commonui.postArg.proc(<楼号>, …, 'a,<推荐值>,c', …)` 三元组中
——已经 20/20 楼与渲染值逐楼对照验证。

做法：按主题从最后一页往回走（走至该题「已收最旧楼」所在页为止——全帖拉取题走到底，
窗口题只走窗口段）；用生产取页路径（PageFetcher，read.php 走 HTTP 快路径）取原始体，
解析三元组与 DOM 锚点，仅 UPDATE 发生变化的行；可断点续跑（进度 JSON）。
收尾：把 reply.recommendvalue 同步进统一 post 表 recommend 列（同步器只插不更）。

用法：
    venv/bin/python backfill_recommend.py             # 全量（566 主题，可断点续跑）
    venv/bin/python backfill_recommend.py --limit 3   # 冒烟：只跑 3 个主题
    venv/bin/python backfill_recommend.py --tid 47438311
"""
import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from lxml import html as LH
from sqlalchemy import bindparam, text

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from NGA_Scrapy.middlewares import CookieManager, PageFetcher, PlaywrightWorker  # noqa: E402
from NGA_Scrapy.utils.db_utils import create_db_session  # noqa: E402

PROGRESS_FILE = ROOT / 'backfill_recommend_progress.json'
LOG_FILE = ROOT / 'backfill_recommend.log'
FREEZE_TIME = '2026-10-14 01:19'  # R28 冻结时点：之后的楼属停采后新增
PAGE_SLEEP = 0.4                  # 页间节流（对站点低影响）

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()],
)
logger = logging.getLogger('backfill_recommend')


def parse_floor_map(content: str):
    """从 read.php 原始体解析每楼 (楼号, pid, 时间, 推荐值)。

    楼号→pid：DOM 锚点（postcontainer<N> 内的 pid<rid>Anchor；主楼 pid0 → None，调用处补 tid）；
    楼号→推荐值：commonui.postArg.proc 脚本块的三元组 'a,b,c' 取中位（与渲染值对照验证过）；
    楼号→时间：postdate<N> 文本。
    """
    doc = LH.fromstring(content)
    floor_pid, floor_time = {}, {}
    for el in doc.xpath('//*[starts-with(@id, "postcontainer")]'):
        n = (el.get('id') or '').replace('postcontainer', '')
        a = el.xpath('./a[1]/@id')
        if n and a:
            pid = a[0].replace('pid', '').replace('Anchor', '')
            floor_pid[n] = None if pid == '0' else pid
    for el in doc.xpath('//*[starts-with(@id, "postdate")]'):
        n = (el.get('id') or '').replace('postdate', '')
        t = (el.text or '').strip()
        if n and t:
            floor_time[n] = t
    floor_rec = {}
    for m in re.finditer(r"commonui\.postArg\.proc\(\s*(\d+),(.*?)if\(", content, re.S):
        triples = re.findall(r"'(\d+),(\d+),(\d+)'", m.group(2))
        if triples:
            floor_rec[m.group(1)] = triples[-1][1]
    return [(n, floor_pid[n], floor_time.get(n), floor_rec.get(n)) for n in floor_pid]


def parse_total_page(content: str):
    m = re.search(r"var __PAGE\s*=\s*\{0:'[^']*',1:(\d+),2:(\d+),3:\d+\}", content)
    if m:
        return int(m.group(1))
    # 无 __PAGE（2026-10-14 修）：单页帖的页面不含分页 UI，服务端对 page=999 clamp 到第 1 页。
    # 此前只认 __PAGE，把 227 个内容完整的单页短帖误记为「不可得」。
    # 回退判据与爬虫一致（nga_spider.py 三级回退）：是帖子内容页时，page= 链接取 max，无则 1；
    # 非内容页（删除/锁定/审核）返回 None，由调用处按页面标题记因。
    if 'postcontainer' not in content or 'commonui.postArg' not in content:
        return None
    pages = [int(x) for h in LH.fromstring(content).xpath('//a[contains(@href, "page=")]/@href')
             for x in re.findall(r'page=(\d+)', h)]
    return max(pages) if pages else 1


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding='utf-8'))
    return {'topics': {}, 'started': datetime.now().isoformat()}


def save_progress(p: dict):
    PROGRESS_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding='utf-8')


SELECT_CUR = text('SELECT rid, recommendvalue FROM reply WHERE rid IN :rids') \
    .bindparams(bindparam('rids', expanding=True))
UPDATE_REC = text('UPDATE reply SET recommendvalue = :v WHERE rid = :rid')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 个主题（冒烟）')
    ap.add_argument('--tid', type=str, default='', help='只跑指定 tid')
    args = ap.parse_args()

    session = create_db_session()
    if session is None:
        logger.error('数据库会话创建失败')
        return 2

    topics = session.execute(text(
        'SELECT t.tid, count(r.rid) AS n, min(r.post_time) AS tmin '
        'FROM topic t LEFT JOIN reply r ON r.tid = t.tid '
        'GROUP BY t.tid HAVING count(r.rid) > 0 ORDER BY count(r.rid) ASC'
    )).mappings().all()
    if args.tid:
        topics = [t for t in topics if t['tid'] == args.tid]
    if args.limit:
        topics = topics[:args.limit]
    logger.info(f'待回填主题: {len(topics)}')

    cm = CookieManager(logger)
    cookies = cm.load(str(ROOT / 'cookies.txt'))
    worker = PlaywrightWorker(max_browsers=1, logger=logger, proxy_manager=None)
    fetcher = PageFetcher(logger)

    def fetch(url):
        def task(pool):
            return fetcher.fetch(pool, url, cookies, 0)
        return worker.execute(task)

    progress = load_progress()
    totals = {'topics_done': 0, 'pages': 0, 'floors': 0, 'updated': 0, 'same': 0,
              'no_triple': 0, 'not_in_db_new': 0, 'not_in_db_gap': 0,
              'not_in_db_outside': 0, 'errors': 0}

    try:
        for i, t in enumerate(topics, 1):
            tid, tmin = t['tid'], (t['tmin'] or '')
            st = progress['topics'].get(tid) or {}
            if st.get('done'):
                continue
            logger.info(f"[{i}/{len(topics)}] tid={tid} 已收 {t['n']} 楼，最旧 {tmin}")
            try:
                first = fetch(f'https://bbs.nga.cn/read.php?tid={tid}&page=999')
                content = first['content']
                total = parse_total_page(content)
                if total is None:
                    # 记录失败面：删除/超时限锁（不可得）与瞬时异常（重试可取）都落在这一支
                    tm = re.search(r'<title>(.*?)</title>', content, re.S)
                    note = (tm.group(1).strip()[:40] if tm else '无标题') or '无标题'
                    logger.warning(f'  tid={tid}: __PAGE 未解析出总页数（页面标题: {note}），跳过')
                    progress['topics'][tid] = {'done': True, 'note': f'no_page_count: {note}'}
                    save_progress(progress)
                    continue
                page = total
                while page and page >= 1:
                    if page != total:
                        content = fetch(
                            f'https://bbs.nga.cn/read.php?tid={tid}&page={page}')['content']
                    floors = parse_floor_map(content)
                    totals['pages'] += 1
                    totals['floors'] += len(floors)

                    rid_map, page_times = {}, []
                    for n, pid, ptime, rec in floors:
                        rid = pid or tid
                        if rec is None:
                            totals['no_triple'] += 1
                        else:
                            rid_map[rid] = int(rec) if rec != '\xa0' else 0
                        if ptime:
                            page_times.append(ptime)

                    rids = list(rid_map.keys())
                    cur = {}
                    if rids:
                        for row in session.execute(SELECT_CUR, {'rids': rids}).mappings():
                            cur[row['rid']] = row['recommendvalue']

                    to_update = []
                    for rid, v in rid_map.items():
                        if rid in cur:
                            if cur[rid] != v:
                                to_update.append((rid, v))
                            else:
                                totals['same'] += 1
                        else:
                            pt = next((ptime for n, pid, ptime, rec in floors
                                       if (pid or tid) == rid), None)
                            if pt and pt > FREEZE_TIME:
                                totals['not_in_db_new'] += 1
                            elif pt and tmin and pt < tmin:
                                totals['not_in_db_outside'] += 1
                            else:
                                totals['not_in_db_gap'] += 1
                                logger.warning(f'  缺口候选: tid={tid} rid={rid} time={pt}')

                    for rid, v in to_update:
                        session.execute(UPDATE_REC, {'v': v, 'rid': rid})
                    session.commit()
                    totals['updated'] += len(to_update)

                    # 停止判定：本页全部楼都早于该题已收最旧楼 → 再往前的页不含已收楼
                    if page_times and tmin and max(page_times) < tmin:
                        logger.info(f'  tid={tid}: 第 {page} 页全早于 {tmin}，停止下探')
                        break
                    page -= 1
                    time.sleep(PAGE_SLEEP)
                progress['topics'][tid] = {'done': True}
                totals['topics_done'] += 1
            except KeyboardInterrupt:
                raise
            except Exception as e:
                totals['errors'] += 1
                logger.error(f'  tid={tid} 处理失败: {type(e).__name__}: {e}')
                progress['topics'][tid] = {'done': False, 'note': f'{type(e).__name__}: {e}'}
            save_progress(progress)
            if i % 10 == 0:
                logger.info(f'进度: {totals}')
    except KeyboardInterrupt:
        logger.warning('中断——进度已保存，可重跑续传')
    finally:
        # 收尾：同步 post 表 recommend 列（只在全量运行时做；冒烟不动）
        if args.limit == 0 and not args.tid:
            n = session.execute(text(
                "UPDATE post p SET recommend = r.recommendvalue FROM reply r "
                "WHERE p.platform = 'nga' AND p.unit_id = r.rid "
                "AND p.recommend IS DISTINCT FROM r.recommendvalue")).rowcount
            session.commit()
            logger.info(f'post 表 recommend 同步: {n} 行')
        logger.info(f'回填结束: {totals}')
        worker.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
