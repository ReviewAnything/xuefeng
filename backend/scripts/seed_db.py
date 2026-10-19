"""手动播种 / 重建数据库（管理端「数据同步」的命令行等价物）。

用法：
    python scripts/seed_db.py                      # 按文件签名增量同步
    python scripts/seed_db.py --force              # 忽略签名，全量重灌
    python scripts/seed_db.py --targets admission  # 只同步录取基线
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import init_db                     # noqa: E402
from db import seed as seed_mod            # noqa: E402
from db import repository as repo          # noqa: E402
from services import admission as A        # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="xuefeng 数据落库播种")
    parser.add_argument("--force", action="store_true", help="忽略文件签名，强制全量重灌")
    parser.add_argument("--targets", default="", help="逗号分隔：universities,admission,content,admin")
    args = parser.parse_args()

    targets = [t.strip() for t in args.targets.split(",") if t.strip()] or None
    init_db(seed=False)
    stats = seed_mod.sync_all(targets=targets, force=args.force)
    A.invalidate_cache()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("数据库：", repo.db_info())
    print("院校：", repo.university_counts())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
