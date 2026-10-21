#!/usr/bin/env python3
"""把 data/rank_tables/ 的官方一分一段 JSON 落库到 rank_segments。

实际写入逻辑在 ``services/rank_store.py``（管理端「一键同步」也走它），
本文件只做批量 CLI：``--all`` 全量、``--year`` 指定年份。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import init_db  # noqa: E402
from services import rank_store as RS  # noqa: E402

DATA = RS.DATA


def import_file(path: Path) -> dict:
    return RS.import_file(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="导入 data/rank_tables 全部年份")
    ap.add_argument("--year", type=int, default=0, help="只导入指定年份")
    args = ap.parse_args()

    init_db(seed=True)
    files = sorted(DATA.glob("*/*.json"))
    if args.year:
        files = [f for f in files if f.parent.name == str(args.year)]
    if not files:
        print("没有可导入的 rank_tables JSON")
        return 0
    ok = True
    for f in files:
        try:
            print("OK ", f.relative_to(DATA.parent), import_file(f))
        except Exception as e:  # noqa: BLE001
            ok = False
            print("FAIL", f.relative_to(DATA.parent), e)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
