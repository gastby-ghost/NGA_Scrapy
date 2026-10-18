#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_from_staging.py — 把服务器快照合并进本地主库（2026-10-18）

源库：nga_scrapy_live（由 scripts/restore_local.sh 从服务器备份恢复的快照）
目标库：nga_scrapy（本地研究库）

合并策略：按表主键 UPSERT。
- 快照里新增的行：插入
- 主键已存在的行：用快照的值覆盖（云端持续采集，同一帖子的回复数、
  推荐值、最后回复时间都会更新；快照是更新的状态）
- 本地独有的行：保留，不删除

用法：
    ./venv/bin/python scripts/merge_from_staging.py
    ./venv/bin/python scripts/merge_from_staging.py --source nga_scrapy_live --target nga_scrapy
"""

import argparse
import io
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

import psycopg2
from database_config import POSTGRES_CONFIG


def connect(dbname):
    return psycopg2.connect(
        host=POSTGRES_CONFIG['host'],
        port=POSTGRES_CONFIG['port'],
        user=POSTGRES_CONFIG['user'],
        password=POSTGRES_CONFIG['password'],
        dbname=dbname,
    )


def quote(ident):
    return '"' + ident.replace('"', '""') + '"'


def get_columns(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def get_pk(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
            """,
            (quote(table),),
        )
        return [r[0] for r in cur.fetchall()]


def merge_table(src, dst, table):
    """把 src.table 全量 COPY 到 dst 的临时表，再按主键 UPSERT。返回 (前, 后)。"""
    cols = get_columns(dst, table)
    pk = get_pk(dst, table)
    if not cols or not pk:
        print(f"  [跳过] {table}: 目标库无此表或无主键")
        return None

    col_list = ", ".join(quote(c) for c in cols)
    upd_cols = [c for c in cols if c not in pk]
    if upd_cols:
        set_clause = ", ".join(f"{quote(c)} = EXCLUDED.{quote(c)}" for c in upd_cols)
        conflict = (f"ON CONFLICT ({', '.join(quote(c) for c in pk)}) "
                    f"DO UPDATE SET {set_clause}")
    else:
        conflict = f"ON CONFLICT ({', '.join(quote(c) for c in pk)}) DO NOTHING"

    with dst.cursor() as dc:
        dc.execute(f"SELECT count(*) FROM {quote(table)}")
        before = dc.fetchone()[0]

    with src.cursor() as sc, dst.cursor() as dc:
        dc.execute(f"CREATE TEMP TABLE _merge_tmp (LIKE {quote(table)} INCLUDING DEFAULTS) ON COMMIT DROP")
        buf = io.StringIO()
        sc.copy_expert(f"COPY (SELECT {col_list} FROM {quote(table)}) TO STDOUT WITH CSV", buf)
        buf.seek(0)
        dc.copy_expert(
            f"COPY _merge_tmp ({col_list}) FROM STDIN WITH CSV", buf)
        dc.execute(
            f"INSERT INTO {quote(table)} ({col_list}) "
            f"SELECT {col_list} FROM _merge_tmp {conflict}"
        )
        affected = dc.rowcount

    dst.commit()
    with dst.cursor() as dc:
        dc.execute(f"SELECT count(*) FROM {quote(table)}")
        after = dc.fetchone()[0]
    added = after - before
    print(f"  {table}: {before:,} -> {after:,}（新增 {added:,}，更新 {affected - added:,}）")
    return before, after


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default='nga_scrapy_live', help='快照库名（默认 nga_scrapy_live）')
    ap.add_argument('--target', default=POSTGRES_CONFIG['database'], help='目标库名（默认 .env 的 POSTGRES_DB）')
    args = ap.parse_args()

    if args.source == args.target:
        sys.exit('源库与目标库相同，拒绝执行')

    print(f"合并 {args.source} -> {args.target}")
    src = connect(args.source)
    dst = connect(args.target)
    try:
        # 按依赖顺序：user/topic 先于 reply/post
        for table in ('user', 'topic', 'reply', 'post', 'monitor_thread'):
            merge_table(src, dst, table)
    finally:
        src.close()
        dst.close()

    # 核对
    conn = connect(args.target)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), max(sampling_time) FROM reply")
        n, latest = cur.fetchone()
    conn.close()
    print(f"完成：目标库 reply {n:,} 条，最新采样 {latest}")

if __name__ == '__main__':
    main()
