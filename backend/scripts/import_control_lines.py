"""将近五年官方省控线落库到 admission_baselines（按真实年份分版本）。

用法（在 backend/ 目录下执行）：
    python scripts/import_control_lines.py            # 导入 2022–2025（跳过当前生效年份，避免扰动实时排名）
    python scripts/import_control_lines.py --dry-run  # 只统计，不写库
    python scripts/import_control_lines.py --all-years  # 连生效年份也导入（会覆盖该年估算行，慎用）

安全约束：
  - 仅 INSERT，绝不 UPDATE 已存在的 (year,province,subject,tier) 行，幂等可重复跑。
  - 默认跳过「当前生效年份」（active_year），因为该年行正驱动按位次的冲稳保实时排名；
    省控线主表不含位次，落为 official 且 min_rank=0 会拉垮排名，故不默认覆盖。
  - 生效年份的官方省控线仍可由 JSON 经 /api/admission/control-lines 按年浏览（年度罗盘）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from db import repository as repo
from db.database import init_db, session_scope
from db.models import AdmissionBaseline

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "admission_control_lines_2022_2026.json")


def main() -> int:
    ap = argparse.ArgumentParser(description="导入近五年官方省控线到 admission_baselines")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    ap.add_argument("--all-years", action="store_true", help="连生效年份也导入（覆盖估算行，慎用）")
    ap.add_argument("--year", type=int, help="只导入指定年份")
    args = ap.parse_args()

    init_db(seed=False)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    active = repo.active_year()
    print(f"当前生效年份(active_year)：{active}")

    sources = data.get("meta", {}).get("sources", {})
    by_year = data.get("by_year", {})

    total_inserted = 0
    total_skipped = 0
    plan = []  # (year, action)

    for y in data.get("meta", {}).get("years", []):
        if args.year and int(y) != args.year:
            continue
        year = int(y)
        if year == active and not args.all_years:
            plan.append((year, "skip(active)"))
            continue
        batch = by_year.get(str(year), {}).get("batch_lines", {})
        rows = []
        for province, subjects in batch.items():
            for subject, tiers in subjects.items():
                for tier, o in tiers.items():
                    rows.append({
                        "year": year, "province": province, "subject": subject, "tier": tier,
                        "min_score": int(o["score"]), "min_rank": 0,
                        "data_source": "official", "line": o.get("line", ""), "school": "",
                        "source_year": year, "carried": False,
                        "source_url": sources.get(str(year), ""),
                    })
        plan.append((year, f"{len(rows)} 行待导入"))

        if args.dry_run:
            total_skipped += len(rows)
            continue

        with session_scope() as s:
            existing = {(r.year, r.province, r.subject, r.tier): r
                        for r in s.scalars(select(AdmissionBaseline)).all()}
            inserted = upgraded = 0
            for row in rows:
                key = (row["year"], row["province"], row["subject"], row["tier"])
                ex = existing.get(key)
                if ex is None:
                    s.add(AdmissionBaseline(**row))
                    inserted += 1
                    total_inserted += 1
                elif ex.data_source != "official" and row["data_source"] == "official":
                    # 官方覆盖层允许覆盖同主键的 estimated 行（历史年份 min_rank=0 不影响实时排名）
                    for k, v in row.items():
                        setattr(ex, k, v)
                    upgraded += 1
                    total_inserted += 1
                else:
                    total_skipped += 1
            # 刷新阈值缓存
            repo.invalidate()
        print(f"  {year}: 插入 {inserted} 行，升级估算→官方 {upgraded} 行，"
              f"跳过已存在 {len(rows) - inserted - upgraded} 行")

    print("\n导入计划：")
    for y, a in plan:
        print(f"  {y}: {a}")
    print(f"\n合计：新增 {total_inserted} 行，跳过 {total_skipped} 行"
          + ("（dry-run，未写库）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
