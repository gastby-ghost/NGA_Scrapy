# verify_data.py
"""数据自检：NGA 采集质量 + 统一记录表同步 + 多平台监测活性。

用法（项目根目录）：venv/bin/python verify_data.py
几天长跑期间可随时执行；取数/导出前建议先跑一遍。异常项以 ✗/⚠ 标出，退出码非零表示需处理。
"""
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from sqlalchemy import create_engine, text

from database_config import get_database_url, get_engine_args

problems = []


def fmt_ago(iso_str):
    if not iso_str:
        return '(无)'
    try:
        dt = datetime.strptime(iso_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return f'(格式异常: {iso_str})'
    mins = (datetime.now(timezone.utc) - dt).total_seconds() / 60
    if mins < 90:
        return f'{mins:.0f} 分钟前'
    return f'{mins / 60:.1f} 小时前'


def main():
    engine = create_engine(get_database_url(), **get_engine_args())
    with engine.connect() as conn:
        q = lambda sql: conn.execute(text(sql)).scalar()

        print(f"===== 数据自检 {datetime.now().strftime('%F %T')} =====")

        # NGA 采集质量
        total = q("SELECT count(*) FROM reply")
        empty = q("SELECT count(*) FROM reply WHERE content IS NULL OR content=''")
        parents = q("SELECT count(*) FROM reply WHERE parent_rid IS NOT NULL AND parent_rid!=''")
        img_urls = q("SELECT count(*) FROM reply WHERE image_urls::text NOT IN ('[]', 'null')")
        img_paths = q("SELECT count(*) FROM reply WHERE image_paths::text NOT IN ('[]', 'null')")
        last_batch = q("SELECT max(sampling_time) FROM reply")
        print("【NGA 采集】")
        print(f"  reply 总数 {total:,} | 空正文 {empty} | 有回复关系 {parents:,} ({parents / max(total, 1) * 100:.1f}%)")
        print(f"  有图 URL {img_urls:,} 楼 | 已落盘 {img_paths:,} 楼")
        print(f"  最近采样 {last_batch}")
        if empty > 0:
            problems.append(f"NGA 空正文 {empty} 条（提取回归信号）")
        if img_urls - img_paths > 50:
            problems.append(f"有图 URL 未落盘 {img_urls - img_paths} 楼（可跑 backfill_images.py 回填）")

        # NGA → post 同步
        nga_post = q("SELECT count(*) FROM post WHERE platform='nga'")
        backlog = q("""SELECT count(*) FROM reply r
                       LEFT JOIN post p ON p.platform='nga' AND p.unit_id=r.rid
                       WHERE p.unit_id IS NULL""")
        nga_sync_seen = q("SELECT max(last_seen) FROM post WHERE platform='nga'")
        print("【统一记录表 post】")
        print(f"  nga {nga_post:,}（待同步积压 {backlog:,}，最近同步 {fmt_ago(nga_sync_seen)}）")

        # 多平台监测
        print("【多平台监测】")
        for plat in ('hn', 'discourse'):
            cnt = q(f"SELECT count(*) FROM post WHERE platform='{plat}'")
            seen = q(f"SELECT max(last_seen) FROM post WHERE platform='{plat}'")
            tracking = q(f"SELECT count(*) FROM monitor_thread WHERE platform='{plat}' AND status='tracking'")
            cooled = q(f"SELECT count(*) FROM monitor_thread WHERE platform='{plat}' AND status='cooled'")
            done = q(f"SELECT count(*) FROM monitor_thread WHERE platform='{plat}' AND status='done'")
            print(f"  {plat:<10} 共 {cnt:,} 楼 | 追踪中 {tracking} / 冷却 {cooled} / 完结 {done} | 最近刷新 {fmt_ago(seen)}")
            if seen:
                dt = datetime.strptime(seen, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - dt).total_seconds() > 2 * 3600:
                    problems.append(f"{plat} 超过 2 小时未刷新（监测轮是否在跑？）")

    engine.dispose()
    if problems:
        print("\n⚠ 需留意：")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)
    print("\n✓ 全部正常")


if __name__ == '__main__':
    main()
