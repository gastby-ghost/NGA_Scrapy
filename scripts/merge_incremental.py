#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_incremental.py — 应用服务器增量包到本地主库（2026-10-18）

增量包由服务器 scripts/export_incremental.py 生成（tar.gz 内每表一个 CSV）。
按表主键 UPSERT 到 .env 指定的本地库；冲突时以增量包的值为准。

用法：
    ./venv/bin/python scripts/merge_incremental.py <增量包.tar.gz> [更多包...]
"""

import glob
import json
import os
import sys
import tarfile
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

import psycopg2
from database_config import POSTGRES_CONFIG

TABLES = ['user', 'topic', 'reply', 'post', 'monitor_thread']


def connect():
    return psycopg2.connect(
        host=POSTGRES_CONFIG['host'], port=POSTGRES_CONFIG['port'],
        user=POSTGRES_CONFIG['user'], password=POSTGRES_CONFIG['password'],
        dbname=POSTGRES_CONFIG['database'])


def quote(ident):
    return '"' + ident.replace('"', '""') + '"'


def get_columns(cur, table):
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,))
    return [r[0] for r in cur.fetchall()]


def get_pk(cur, table):
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
        ORDER BY array_position(i.indkey, a.attnum)
        """, (quote(table),))
    return [r[0] for r in cur.fetchall()]


def merge_csv(conn, table, csv_path):
    with conn.cursor() as cur:
        cols = get_columns(cur, table)
        pk = get_pk(cur, table)
        if not cols or not pk:
            print(f'  [跳过] {table}: 目标库无此表或无主键')
            return 0
        col_list = ', '.join(quote(c) for c in cols)
        upd = [c for c in cols if c not in pk]
        conflict = (f"ON CONFLICT ({', '.join(quote(c) for c in pk)}) DO UPDATE SET "
                    + ', '.join(f"{quote(c)} = EXCLUDED.{quote(c)}" for c in upd)) if upd else \
                   f"ON CONFLICT ({', '.join(quote(c) for c in pk)}) DO NOTHING"

        cur.execute(f"SELECT count(*) FROM {quote(table)}")
        before = cur.fetchone()[0]
        cur.execute(f"CREATE TEMP TABLE _inc_tmp (LIKE {quote(table)} INCLUDING DEFAULTS) ON COMMIT DROP")
        with open(csv_path, encoding='utf-8') as f:
            cur.copy_expert(f"COPY _inc_tmp ({col_list}) FROM STDIN WITH CSV HEADER", f)
        cur.execute(
            f"INSERT INTO {quote(table)} ({col_list}) "
            f"SELECT {col_list} FROM _inc_tmp {conflict}")
        affected = cur.rowcount
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {quote(table)}")
        after = cur.fetchone()[0]
    added = after - before
    print(f'  {table}: {before:,} -> {after:,}（新增 {added:,}，更新 {affected - added:,}）')
    return after


def apply_package(conn, package):
    print(f'应用 {os.path.basename(package)}')
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(package, 'r:gz') as tar:
            tar.extractall(tmp)
        for table in TABLES:
            csv_path = os.path.join(tmp, f'{table}.csv')
            if os.path.exists(csv_path):
                merge_csv(conn, table, csv_path)


def main():
    args = sys.argv[1:]
    auto_dir = None
    applied_file = None
    applied = []

    if args and args[0] == '--auto':
        if len(args) < 2:
            sys.exit('用法: merge_incremental.py --auto <增量目录>')
        auto_dir = args[1]
        applied_file = os.path.join(auto_dir, '.applied.json')
        if os.path.exists(applied_file):
            with open(applied_file, encoding='utf-8') as f:
                applied = json.load(f)
        all_pkgs = sorted(glob.glob(os.path.join(auto_dir, 'nga_inc_*.tar.gz')))
        packages = [p for p in all_pkgs if os.path.basename(p) not in applied]
        if not packages:
            print('没有新的增量包')
            return
    else:
        packages = args

    if not packages:
        sys.exit('用法: merge_incremental.py <增量包.tar.gz> [更多包...] 或 --auto <目录>')

    conn = connect()
    try:
        for package in packages:
            apply_package(conn, package)
    finally:
        conn.close()

    if applied_file:
        applied.extend(os.path.basename(p) for p in packages)
        with open(applied_file, 'w', encoding='utf-8') as f:
            json.dump(applied, f, ensure_ascii=False, indent=2)

    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT count(*), max(sampling_time) FROM reply")
        n, latest = cur.fetchone()
    print(f'完成：reply {n:,} 条，最新采样 {latest}')


if __name__ == '__main__':
    main()
