# monitors/run.py
"""多平台监测轮入口（调度器每 30 分钟调用；也可手动执行）。

用法（在项目根目录下）：
  venv/bin/python monitors/run.py                  # 全部：NGA 同步 + HN + Discourse 各一轮
  venv/bin/python monitors/run.py --platform hn    # 只跑 HN（可重复指定）
  venv/bin/python monitors/run.py --sync-only      # 只做 NGA reply → post 同步
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import yaml
from sqlalchemy import create_engine

from database_config import get_database_url, get_engine_args

logger = logging.getLogger('monitors')

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
START_STAMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.started_at')


def load_config():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def monitor_window_open(cfg):
    """监测窗口（duration_days）：首次运行落时间戳；超期后监测轮自动跳过。null=持续运行。"""
    days = cfg.get('duration_days')
    if not days:
        return True
    if not os.path.exists(START_STAMP):
        with open(START_STAMP, 'w', encoding='utf-8') as f:
            f.write(datetime.now(timezone.utc).isoformat())
        return True
    with open(START_STAMP, encoding='utf-8') as f:
        started = datetime.fromisoformat(f.read().strip())
    return (datetime.now(timezone.utc) - started).days < days


def run_all(platforms=None, cfg=None):
    """platforms: None=全部平台；[]=不跑平台（只同步）。NGA 同步每轮都做（本地 PG，毫秒级）。"""
    cfg = cfg or load_config()
    if not monitor_window_open(cfg):
        logger.info('监测窗口已到期（duration_days），本轮跳过')
        return
    engine = create_engine(get_database_url(), **get_engine_args())
    try:
        from monitors.nga_sync import sync_nga
        try:
            total, rounds = 0, 0
            while True:  # 循环至补齐（首次会补上万条历史；之后每轮增量几十条）
                n = sync_nga(engine)
                total += n
                rounds += 1
                if n < 5000 or rounds >= 20:
                    break
            if total:
                logger.info(f'[nga_sync] 本轮共同步 {total} 楼（{rounds} 批）')
        except Exception:
            logger.exception('[nga_sync] 同步失败')

        from monitors.hn import HackerNewsMonitor
        from monitors.discourse import DiscourseMonitor
        registry = {'hn': HackerNewsMonitor, 'discourse': DiscourseMonitor}
        for name, cls in registry.items():
            if platforms is not None and name not in platforms:
                continue
            if not cfg['platforms'][name].get('enabled', True):
                continue
            try:
                cls(cfg, engine).run()
            except Exception:
                logger.exception(f'[{name}] 监测轮失败')
    finally:
        engine.dispose()


def main():
    ap = argparse.ArgumentParser(description='多平台论坛监测轮')
    ap.add_argument('--platform', action='append', help='只跑指定平台（可重复）')
    ap.add_argument('--sync-only', action='store_true', help='只做 NGA→post 同步')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    t0 = time.monotonic()
    run_all(platforms=[] if args.sync_only else args.platform)
    logger.info(f'监测轮总耗时 {time.monotonic() - t0:.1f}s')


if __name__ == '__main__':
    main()
