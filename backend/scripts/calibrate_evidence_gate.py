"""证据门槛校准台账（S8-B）。

S7-C 的「≥10 条校线 / ≥5 所院校」是经验值。本脚本把**真实分布**摆出来，
让阈值调整有依据，而不是拍脑袋：

    cd backend && python scripts/calibrate_evidence_gate.py            # 人读报告
    cd backend && python scripts/calibrate_evidence_gate.py --json     # 机器读

输出：
  * 全库各 (省/科类) 的校线条数 / 覆盖院校数分布（最小值、分位、最大值）
  * 在当前三档阈值（thin / full / refute）下，各档命中多少组合、分别是哪些
  * 若把阈值改成别的值，会有多少组合越过「可判断」线（--try 10,5）

设计红线：这个脚本只统计**证据厚度**，不涉及任何「值不值」的判断。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.verify import (  # noqa: E402
    MIN_EVIDENCE_LINES, MIN_EVIDENCE_SCHOOLS, MIN_REFUTE_LINES,
    MIN_REFUTE_SCHOOLS, MIN_THIN_LINES, MIN_THIN_SCHOOLS, gate_profile,
)


def _quantiles(values: list[int]) -> dict:
    if not values:
        return {"min": 0, "p25": 0, "median": 0, "p75": 0, "max": 0}
    s = sorted(values)
    n = len(s)
    return {"min": s[0], "p25": s[max(0, n // 4)], "median": statistics.median(s),
            "p75": s[min(n - 1, n * 3 // 4)], "max": s[-1]}


def _band(lines: int, schools: int, full: tuple[int, int], thin: tuple[int, int]) -> str:
    if lines < thin[0] or schools < thin[1]:
        return "none"
    if lines >= full[0] and schools >= full[1]:
        return "full"
    return "thin"


def main() -> int:
    ap = argparse.ArgumentParser(description="证据门槛校准台账")
    ap.add_argument("--json", action="store_true", help="输出 JSON（供脚本/测试消费）")
    ap.add_argument("--try", dest="try_at", default="", metavar="LINES,SCHOOLS",
                    help="试算另一组 full 阈值，例如 --try 20,10")
    args = ap.parse_args()

    prof = gate_profile()
    if not prof["combos"]:
        print("库内暂无院校投档线（school_lines 为空），无法校准。")
        return 1

    lines_q = _quantiles([d["lines"] for d in prof["detail"]])
    schools_q = _quantiles([d["schools"] for d in prof["detail"]])
    out = {
        "thresholds": prof["thresholds"],
        "combos": prof["combos"],
        "bands": prof["bands"],
        "distribution": {"lines": lines_q, "schools": schools_q},
    }

    if args.try_at:
        try:
            tl, ts = (int(x) for x in args.try_at.split(","))
        except ValueError:
            print("--try 需形如 20,10", file=sys.stderr)
            return 2
        hits = {"full": 0, "thin": 0, "none": 0}
        for d in prof["detail"]:
            hits[_band(d["lines"], d["schools"], (tl, ts),
                       tuple(prof["thresholds"]["thin"]))] += 1
        out["trial"] = {"full_threshold": [tl, ts], "bands": hits}

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    th = prof["thresholds"]
    print("=" * 68)
    print("证据门槛校准台账（S8-B）")
    print("=" * 68)
    print(f"组合数（省 × 科类）：{prof['combos']}")
    print()
    print("-- 真实分布 --")
    print(f"校线条数   min {lines_q['min']:>5} | p25 {lines_q['p25']:>5} | 中位 {lines_q['median']:>6.0f} "
          f"| p75 {lines_q['p75']:>5} | max {lines_q['max']:>5}")
    print(f"覆盖院校数 min {schools_q['min']:>5} | p25 {schools_q['p25']:>5} | 中位 {schools_q['median']:>6.0f} "
          f"| p75 {schools_q['p75']:>5} | max {schools_q['max']:>5}")
    print()
    print("-- 当前阈值 --")
    print(f"  thin（近乎无样本）  < {th['thin'][0]} 条 或 < {th['thin'][1]} 所 → 不下判断")
    print(f"  full（可判断）      ≥ {th['full'][0]} 条 且 ≥ {th['full'][1]} 所")
    print(f"  refute（全称否定）  ≥ {th['refute'][0]} 条 且 ≥ {th['refute'][1]} 所")
    print()
    print("-- 各档命中 --")
    for band, label in (("full", "可判断"), ("thin", "偏薄（仅方向性提示）"), ("none", "近乎无样本")):
        print(f"  {band:<5} {label:<22} {prof['bands'][band]:>3} 个组合")
    thin_list = [d for d in prof["detail"] if d["band"] != "full"]
    if thin_list:
        print()
        print("-- 未达「可判断」线的组合 --")
        for d in sorted(thin_list, key=lambda x: x["lines"]):
            print(f"  {d['province']:<8} {d['subject']:<8} {d['lines']:>5} 条 / {d['schools']:>4} 所 → {d['band']}")
    else:
        print()
        print("  当前数据下全部组合都在「可判断」档——门槛只在稀疏导入（如官方试点几行）时才会触发。")
    if "trial" in out:
        print()
        print(f"-- 试算 full={out['trial']['full_threshold']} --")
        print(f"  可判断 {out['trial']['bands']['full']} / 偏薄 {out['trial']['bands']['thin']} "
              f"/ 无样本 {out['trial']['bands']['none']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
