"""CLI：``python -m rank_sync [省份...] [--year 2025] [--dry-run]``

不带省份参数时只打印看板（哪些省 ready / 已落盘哪些年），不发起抓取。
"""
from __future__ import annotations

import argparse
import sys

from . import ALL_PROVINCES, overview, sync


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按省同步一分一段表")
    ap.add_argument("provinces", nargs="*", help="省份名（留空=只看板）")
    ap.add_argument("--year", type=int, action="append", default=[], help="只同步指定年份，可重复")
    ap.add_argument("--dry-run", action="store_true", help="只解析校验，不落盘")
    args = ap.parse_args(argv)

    if not args.provinces:
        ov = overview()
        print(f"{'省份':<6}{'状态':<9}{'已落盘':<26}{'适配器年份'}")
        for r in ov["provinces"]:
            cov = ",".join(str(y) for y in r["covered_years"]) or "-"
            yrs = ",".join(str(y) for y in r["years"]) or "-"
            # 列宽要容得下「5 个年份 + 逗号」= 23 字符，否则两列会黏在一起
            print(f"{r['province']:<6}{r['status']:<9}{cov:<26}{yrs}")
        print("\n统计:", ov["counts"], "已覆盖省·年:", ov["covered_province_years"])
        return 0

    bad = [p for p in args.provinces if p not in ALL_PROVINCES]
    if bad:
        print("未知省份:", "、".join(bad))
        return 2

    rc = 0
    for prov in args.provinces:
        rep = sync(prov, years=args.year or None, dry_run=args.dry_run)
        if rep.get("error"):
            print(f"SKIP {prov}: {rep['error']}")
            rc = 1
            continue
        for r in rep["years"]:
            if r.get("ok"):
                print(f"OK   {prov} {r['year']}  rows={r['rows']}  {r['subjects']}")
            else:
                tag = "GAP " if r.get("skipped") else "FAIL"
                print(f"{tag} {prov} {r.get('year')}: {r.get('error')}")
        if not rep["ok"]:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
