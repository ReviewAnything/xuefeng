"""数据库备份（D3）：WAL checkpoint + 一致性快照 + 保留 N 份。

用法（在 backend/ 目录下执行）：

    python scripts/backup_db.py                     # 备份到 backend/backups/
    python scripts/backup_db.py --dir /var/backups --keep 14 --gzip

为什么不是直接 cp
----------------
SQLite 开着 WAL 时，直接复制 .db 可能漏掉未落盘的 -wal 内容。
这里先 `PRAGMA wal_checkpoint(TRUNCATE)`，再用 sqlite3 的在线备份 API
（`Connection.backup`）生成一致的快照，运行中也能安全备份。
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import BASE_DIR, database_url  # noqa: E402


def _db_path() -> str:
    url = database_url()
    if not url.startswith("sqlite:"):
        raise SystemExit(f"当前数据库不是 SQLite（{url.split('://')[0]}），请用 pg_dump 之类的工具备份")
    path = url.split("sqlite:///", 1)[-1]
    if not os.path.exists(path):
        raise SystemExit(f"数据库文件不存在：{path}")
    return path


def backup(out_dir: str, keep: int = 7, compress: bool = False) -> dict:
    src = _db_path()
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"xuefeng-{stamp}.db"
    tmp = os.path.join(out_dir, name)

    con = sqlite3.connect(src)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        dst = sqlite3.connect(tmp)
        try:
            con.backup(dst)          # 在线一致性备份
        finally:
            dst.close()
    finally:
        con.close()

    final = tmp
    if compress:
        final = tmp + ".gz"
        with open(tmp, "rb") as f, gzip.open(final, "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g)
        os.remove(tmp)

    # 只保留最近 keep 份（按文件名里时间戳排序，天然有序）
    files = sorted(f for f in os.listdir(out_dir) if f.startswith("xuefeng-") and f.endswith((".db", ".db.gz")))
    removed = []
    for old in files[:-keep] if keep > 0 else []:
        os.remove(os.path.join(out_dir, old))
        removed.append(old)

    return {
        "ok": True,
        "source": src,
        "source_kb": round(os.path.getsize(src) / 1024, 1),
        "backup": final,
        "backup_kb": round(os.path.getsize(final) / 1024, 1),
        "kept": [f for f in files if f not in removed],
        "removed": removed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="SQLite 一致性备份 + 保留策略")
    ap.add_argument("--dir", default=os.path.join(BASE_DIR, "backups"), help="备份目录")
    ap.add_argument("--keep", type=int, default=7, help="保留份数（0 表示不清理）")
    ap.add_argument("--gzip", action="store_true", help="压缩为 .db.gz（体积约 1/5）")
    args = ap.parse_args()
    result = backup(args.dir, keep=args.keep, compress=args.gzip)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
