#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_incremental.py — 服务器端每日增量导出（2026-10-18）

按水位导出变更行，打包为 incremental/nga_inc_YYYY-MM-DD_HHMM.tar.gz：
- reply / topic：sampling_time > 水位（重抓的旧行也会刷新 sampling_time）
- post：last_seen > 水位
- monitor_thread：last_fetched_at > 水位
- user：全量（表小且无更新时间字段，约 2 MB CSV）

水位存 incremental/state.json；首次运行无水位时导出全量作为基线。
保留最近 30 个增量包。

用法：./venv/bin/python scripts/export_incremental.py
"""

import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

import psycopg2
from database_config import POSTGRES_CONFIG

INC_DIR = os.path.join(PROJECT_DIR, 'incremental')
STATE_FILE = os.path.join(INC_DIR, 'state.json')

# (表名, 水位字段; None=全量)
TABLES = [
    ('topic', 'sampling_time'),
    ('reply', 'sampling_time'),
    ('post', 'last_seen'),
    ('monitor_thread', 'last_fetched_at'),
    ('user', None),
]


def quote(ident):
    return '"' + ident.replace('"', '""') + '"'


def main():
    os.makedirs(INC_DIR, exist_ok=True)
    state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding='utf-8') as f:
            state = json.load(f)

    stamp = datetime.now().strftime('%Y-%m-%d_%H%M')
    work = tempfile.mkdtemp(prefix='nga_inc_')
    os.makedirs(work, exist_ok=True)

    conn = psycopg2.connect(
        host=POSTGRES_CONFIG['host'], port=POSTGRES_CONFIG['port'],
        user=POSTGRES_CONFIG['user'], password=POSTGRES_CONFIG['password'],
        dbname=POSTGRES_CONFIG['database'])
    new_state = dict(state)
    counts = {}

    try:
        with conn.cursor() as cur:
            for table, wm_col in TABLES:
                old_wm = state.get(table)
                if wm_col is None:
                    where, params = '', ()
                elif old_wm:
                    where, params = f'WHERE {wm_col} > %s', (old_wm,)
                else:
                    where, params = '', ()  # 首次：全量基线

                if wm_col:
                    cur.execute(f'SELECT max({wm_col}) FROM {quote(table)}')
                    new_wm = cur.fetchone()[0]
                    if new_wm:
                        new_state[table] = new_wm
                        params = (old_wm, new_wm) if old_wm else (new_wm,)
                        where = (f'WHERE {wm_col} > %s AND {wm_col} <= %s' if old_wm
                                 else f'WHERE {wm_col} <= %s')

                path = os.path.join(work, f'{table}.csv')
                sql = (f'COPY (SELECT * FROM {quote(table)} {where}) '
                       'TO STDOUT WITH CSV HEADER')
                sql = cur.mogrify(sql, params)
                if isinstance(sql, bytes):
                    sql = sql.decode()
                with open(path, 'w', encoding='utf-8', newline='') as f:
                    cur.copy_expert(sql, f)
                # 行数按数据库统计——CSV 内容可能含换行，数文件行会虚高
                cur.execute(f'SELECT count(*) FROM {quote(table)} {where}', params)
                counts[table] = cur.fetchone()[0]

        out = os.path.join(INC_DIR, f'nga_inc_{stamp}.tar.gz')
        with tarfile.open(out, 'w:gz') as tar:
            for table, _ in TABLES:
                tar.add(os.path.join(work, f'{table}.csv'), arcname=f'{table}.csv')

        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)

        print(f'[{datetime.now():%F %T}] 增量包: {out}')
        for t, n in counts.items():
            print(f'  {t}: {n:,} 行')

        # 保留最近 30 个增量包
        packages = sorted(
            (os.path.join(INC_DIR, p) for p in os.listdir(INC_DIR)
             if p.startswith('nga_inc_') and p.endswith('.tar.gz')))
        for old in packages[:-30]:
            os.remove(old)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
