#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NGA_Scrapy 数据导出脚本

将数据库、爬取图片、归档数据打包为 .tar.gz，方便从服务器下载。

用法：
    python export_data.py
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

# ============================================================
# 1. 自动安装依赖
# ============================================================

def ensure_dependencies():
    """检测并安装缺失的依赖"""
    required = {
        'psycopg2-binary': 'psycopg2',
        'python-dotenv': 'dotenv',
    }

    missing = []
    for package, import_name in required.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package)

    if missing:
        print(f"[依赖] 安装缺失的包: {', '.join(missing)}")
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install'] + missing,
            check=True,
        )
        print("[依赖] 安装完成")


# ============================================================
# 2. 获取项目路径和数据库配置
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent


def get_db_config():
    """从 database_config.py 读取数据库配置"""
    sys.path.insert(0, str(PROJECT_DIR))

    # 加载 .env
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / '.env')

    from database_config import POSTGRES_CONFIG
    return POSTGRES_CONFIG


# ============================================================
# 3. 清理旧导出
# ============================================================

def clean_old_exports():
    """删除之前的导出文件"""
    pattern = str(PROJECT_DIR / "NGA_Scrapy_导出_*.tar.gz")
    old_files = glob.glob(pattern)

    for f in old_files:
        os.remove(f)
        print(f"[清理] 已删除旧导出: {os.path.basename(f)}")


# ============================================================
# 4. 数据库导出
# ============================================================

def export_db_pg_dump(config, tmp_dir):
    """使用 pg_dump 导出数据库"""
    db_file = tmp_dir / "db_export.sql"
    env = os.environ.copy()
    env['PGPASSWORD'] = config['password']

    cmd = [
        'pg_dump',
        '-h', config['host'],
        '-p', str(config['port']),
        '-U', config['user'],
        '-d', config['database'],
        '-f', str(db_file),
        '--no-password',
    ]

    print(f"[数据库] 使用 pg_dump 导出 {config['database']}...")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[数据库] pg_dump 失败: {result.stderr}")
        return None, None

    size_mb = db_file.stat().st_size / 1024 / 1024
    print(f"[数据库] pg_dump 完成 ({size_mb:.1f} MB)")
    return db_file, "pg_dump"


def export_db_sqlalchemy(config, tmp_dir):
    """使用 SQLAlchemy 回退导出数据库为 JSON"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = (
        f"postgresql://{config['user']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )

    print(f"[数据库] 使用 SQLAlchemy 导出 {config['database']}...")
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        from NGA_Scrapy.models import User, Topic, Reply

        data = {}

        # 导出用户
        users = session.query(User).all()
        data['users'] = [
            {
                'uid': u.uid, 'name': u.name, 'user_group': u.user_group,
                'prestige': u.prestige, 'reg_date': u.reg_date,
                'history_re_num': u.history_re_num,
            }
            for u in users
        ]
        print(f"[数据库] 用户: {len(data['users'])} 条")

        # 导出主题
        topics = session.query(Topic).all()
        data['topics'] = [
            {
                'tid': t.tid, 'title': t.title, 'poster_id': t.poster_id,
                'post_time': t.post_time, 're_num': t.re_num,
                'sampling_time': t.sampling_time,
                'last_reply_date': t.last_reply_date,
                'partition': t.partition,
            }
            for t in topics
        ]
        print(f"[数据库] 主题: {len(data['topics'])} 条")

        # 导出回复
        replies = session.query(Reply).all()
        data['replies'] = [
            {
                'rid': r.rid, 'tid': r.tid, 'parent_rid': r.parent_rid,
                'content': r.content, 'recommendvalue': r.recommendvalue,
                'poster_id': r.poster_id, 'post_time': r.post_time,
                'image_urls': r.image_urls, 'image_paths': r.image_paths,
                'sampling_time': r.sampling_time,
            }
            for r in replies
        ]
        print(f"[数据库] 回复: {len(data['replies'])} 条")

        db_file = tmp_dir / "db_export.json"
        with open(db_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        size_mb = db_file.stat().st_size / 1024 / 1024
        print(f"[数据库] SQLAlchemy 导出完成 ({size_mb:.1f} MB)")
        return db_file, "sqlalchemy_json"

    finally:
        session.close()
        engine.dispose()


def export_database(config, tmp_dir):
    """导出数据库，优先 pg_dump，回退 SQLAlchemy"""
    if shutil.which('pg_dump'):
        result, method = export_db_pg_dump(config, tmp_dir)
        if result:
            return result, method
        print("[数据库] pg_dump 失败，回退到 SQLAlchemy...")

    return export_db_sqlalchemy(config, tmp_dir)


# ============================================================
# 5. 生成元信息
# ============================================================

def create_export_info(db_file, method, config, has_images, has_archive):
    """生成 export_info.json"""
    info = {
        'export_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'export_method': method,
        'database': config['database'],
        'contents': {
            'database': db_file.name,
        },
    }
    if has_images:
        info['contents']['images_dir'] = 'download_images'
    if has_archive:
        info['contents']['archive_dir'] = 'archive'

    return info


# ============================================================
# 6. 打包
# ============================================================

def create_tarball(db_file, export_info, tmp_dir):
    """打包为 .tar.gz"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tarball_name = f"NGA_Scrapy_导出_{timestamp}.tar.gz"
    tarball_path = PROJECT_DIR / tarball_name
    inner_dir = f"NGA_Scrapy_导出_{timestamp}"

    images_dir = PROJECT_DIR / "download_images"
    archive_dir = PROJECT_DIR / "archive"
    has_images = images_dir.is_dir()
    has_archive = archive_dir.is_dir()

    # 更新元信息
    export_info = create_export_info(db_file, export_info['export_method'], export_info['database'], has_images, has_archive)

    # 写入临时 export_info.json
    info_file = tmp_dir / "export_info.json"
    with open(info_file, 'w', encoding='utf-8') as f:
        json.dump(export_info, f, ensure_ascii=False, indent=2)

    print("[打包] 开始压缩...")

    with tarfile.open(tarball_path, 'w:gz') as tar:
        # 数据库导出文件
        tar.add(str(db_file), arcname=f"{inner_dir}/{db_file.name}")
        # 元信息
        tar.add(str(info_file), arcname=f"{inner_dir}/export_info.json")

        # 图片目录
        if has_images:
            tar.add(str(images_dir), arcname=f"{inner_dir}/download_images")
            print(f"[打包] 包含 download_images/")
        else:
            print("[打包] download_images/ 不存在，已跳过")

        # 归档目录
        if has_archive:
            tar.add(str(archive_dir), arcname=f"{inner_dir}/archive")
            print(f"[打包] 包含 archive/")
        else:
            print("[打包] archive/ 不存在，已跳过")

    size_mb = tarball_path.stat().st_size / 1024 / 1024
    print(f"[打包] 完成: {tarball_name} ({size_mb:.1f} MB)")

    return tarball_path


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("NGA_Scrapy 数据导出")
    print("=" * 60)

    # 1. 安装依赖
    ensure_dependencies()

    # 2. 清理旧导出
    clean_old_exports()

    # 3. 创建临时目录
    tmp_dir = PROJECT_DIR / "tmp_export"
    tmp_dir.mkdir(exist_ok=True)

    try:
        # 4. 获取数据库配置
        config = get_db_config()
        print(f"[配置] 数据库: {config['database']}@{config['host']}:{config['port']}")

        # 5. 导出数据库
        db_file, method = export_database(config, tmp_dir)

        # 6. 打包
        tarball_path = create_tarball(db_file, {'export_method': method, 'database': config['database']}, tmp_dir)

        # 7. 输出结果
        print()
        print("=" * 60)
        print("导出完成")
        print("=" * 60)
        print(f"文件: {tarball_path.name}")
        print(f"大小: {tarball_path.stat().st_size / 1024 / 1024:.1f} MB")
        print()
        print("下载命令:")
        rel_path = tarball_path.relative_to(Path.home())
        print(f"  scp USER@HOST:~/{rel_path} .")
        print()

    finally:
        # 8. 清理临时文件
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
