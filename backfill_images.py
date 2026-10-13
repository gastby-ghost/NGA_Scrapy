# backfill_images.py
"""回填「有图 URL 但未落盘」的楼（2026-10-13 图片链修复前批次，约 1,545 楼）。

- 读取 reply 表中 image_urls 非空数组、image_paths 为空的楼
- 逐 URL 下载（图床域重写 nga.178.com → nga.cn，与中间件同规则；图床为 CDN，非论坛本体）
- 落盘 download_images/full/<sha1(url)><ext>（与 scrapy ImagesPipeline 同构命名），回写 image_paths
- 顺序下载 + 间隔节流，可重复执行（已落盘的跳过）

用法：venv/bin/python backfill_images.py [--dry-run]
"""
import argparse
import hashlib
import os
import sys
import time
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import requests
from sqlalchemy import create_engine, text

from database_config import get_database_url, get_engine_args

STORE = os.path.join(BASE_DIR, 'download_images', 'full')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
INTERVAL = 0.3


def ext_of(url):
    p = urlparse(url).path.lower()
    for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'):
        if p.endswith(ext):
            return ext
    return '.jpg'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    engine = create_engine(get_database_url(), **get_engine_args())
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT rid, image_urls::text AS urls FROM reply
            WHERE image_urls::text NOT IN ('[]', 'null')
              AND (image_paths IS NULL OR image_paths::text IN ('[]', 'null'))
        """)).mappings().all()
    if not rows:
        print('没有需要回填的楼 ✓')
        return

    import json
    total_urls = sum(len(json.loads(r['urls'] or '[]')) for r in rows)
    print(f'待回填 {len(rows)} 楼 / {total_urls} 张图；落盘目录 {STORE}')
    if args.dry_run:
        return
    os.makedirs(STORE, exist_ok=True)

    session = requests.Session()
    session.headers['User-Agent'] = UA
    ok_imgs = fail_imgs = done_rows = 0
    t0 = time.monotonic()

    with engine.begin() as conn:
        for i, r in enumerate(rows, 1):
            paths = []
            for url in json.loads(r['urls'] or '[]'):
                fetch_url = url.replace('nga.178.com', 'nga.cn')
                fname = hashlib.sha1(url.encode()).hexdigest() + ext_of(url)
                fpath = os.path.join(STORE, fname)
                rel = os.path.join('download_images', 'full', fname)
                if os.path.exists(fpath):
                    paths.append(rel)
                    ok_imgs += 1
                    continue
                try:
                    time.sleep(INTERVAL)
                    resp = session.get(fetch_url, timeout=20)
                    resp.raise_for_status()
                    with open(fpath, 'wb') as f:
                        f.write(resp.content)
                    paths.append(rel)
                    ok_imgs += 1
                except Exception as e:
                    fail_imgs += 1
                    print(f"  失败 rid={r['rid']} {fetch_url}: {e}")
            if paths:
                conn.execute(text('UPDATE reply SET image_paths = CAST(:p AS JSON) WHERE rid = :rid'),
                             {'p': json.dumps(paths, ensure_ascii=False), 'rid': r['rid']})
                done_rows += 1
            if i % 200 == 0:
                print(f'  进度 {i}/{len(rows)} 楼 | 图成功 {ok_imgs} 失败 {fail_imgs}')

    print(f'完成：{done_rows} 楼回写 image_paths | 图成功 {ok_imgs} / 失败 {fail_imgs} | 耗时 {time.monotonic() - t0:.0f}s')
    engine.dispose()


if __name__ == '__main__':
    main()
