#!/usr/bin/env python3
"""一分一段采集 CLI（兼容入口）。

真正的实现已按省拆到 ``backend/rank_sync/``：
- ``rank_sync/common.py`` —— 抓取/版式/强校验/落盘公共底座；
- ``rank_sync/provinces/<省>.py`` —— 每省一个模块（发现 + 取数 + 解析）；
- ``rank_sync/__init__.py`` —— 31 省看板与按省同步编排。

本文件只保留两个用途，避免历史调用方（脚本/文档/记忆）失效：
1. ``python scripts/scrape_rank_tables.py 广东`` 仍可用；
2. 继续 re-export 解析与校验函数，供测试与外部脚本 import。

新增省份请改 ``rank_sync/provinces/``，不要往这里加代码。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rank_sync import ALL_PROVINCES, overview, sync  # noqa: E402
from rank_sync.common import (  # noqa: E402,F401  re-export 供测试/外部脚本
    N_COLS, N_COLS_SINGLE, OUT_DIR, ROW_TOL, SCORE_PAT, SCORE_UP_PAT,
    _finalize, _page_block_rows, _page_rows, _pdf_rows, _rows_from_lines,
    find_attachments, http_get, http_get_html, now_iso, parse_blocked_pdf,
    parse_gd_pdf, parse_html_table, parse_single_pdf, parse_xls_tracks,
    save, sha256, validate_rows,
)
from rank_sync.provinces.guangdong import subject_of  # noqa: E402,F401


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--dry-run",)]
    dry = "--dry-run" in sys.argv[1:]
    if not args:
        ov = overview()
        print("统计:", ov["counts"], "已覆盖省·年:", ov["covered_province_years"])
        return 0
    ok = True
    for prov in args:
        if prov not in ALL_PROVINCES:
            print(f"未知省份: {prov}")
            ok = False
            continue
        rep = sync(prov, dry_run=dry)
        if rep.get("error"):
            print(f"SKIP {prov}: {rep['error']}")
            ok = False
            continue
        for r in rep["years"]:
            if r.get("ok"):
                print(f"OK  {prov} {r['year']} rows={r['rows']} {r['subjects']}")
            else:
                print(f"{'GAP ' if r.get('skipped') else 'FAIL'} {prov} {r.get('year')}: {r.get('error')}")
        ok = ok and rep["ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
