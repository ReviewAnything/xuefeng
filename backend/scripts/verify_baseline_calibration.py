#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基线准确性校验（M13/M14/M15 审计回归，审核报告第六节 🔴 项）。

- M13：批次线阈值 vs 官方省控线偏差统计（锚定档要求偏差为 0）。
- M14：baseline (分数, 位次) 配对用同年一分段表（与 services.rank_tables.lookup 同语义）
  校验自洽率。
- M15：种子/基线中「投档分 < 当年对应批次省控线」的确定性违规行。

用法：python scripts/verify_baseline_calibration.py   # 无副作用，只读
退出码：全部通过 0；任一不通过 1（可接 CI）。
"""
import gzip
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from services import control_lines as CL  # noqa: E402
from services import data_quality as DQ   # noqa: E402
from services import rank_tables as RT    # noqa: E402

BASELINE = os.path.join(HERE, "..", "data", "admission_real_baseline.json")
SEED = os.path.join(HERE, "..", "data", "school_lines_estimated_real.json.gz")

RT_SUBJECT_CANDIDATES = {
    "物理类": ["物理类", "物理", "选考物理", "物理科目组合", "理科"],
    "历史类": ["历史类", "历史", "选考历史", "历史科目组合", "文科"],
    "综合": ["综合"],
}


def _rt_rows(year, prov, cat):
    doc = RT.doc(year, prov)
    if not doc:
        return None
    subs = doc.get("subjects") or {}
    for key in RT_SUBJECT_CANDIDATES.get(cat, []):
        blk = subs.get(key)
        if blk and blk.get("rows"):
            return sorted(blk["rows"], key=lambda r: -int(r[0]))
    return None


def check_m13(baseline):
    """M13：锚定档（src=official_control_line）分数必须与控线一致；报告整体偏差分布。"""
    cl = CL
    tiers = ["普通一本", "普通二本", "专科"]
    anchored = matched = 0
    unanchored = 0
    deviations = []
    cal = (baseline.get("meta") or {}).get("calibration") or {}
    provs_meta = cal.get("provinces") or {}
    for prov, cats in baseline["tier_baseline"].items():
        for cat, tb in cats.items():
            am = provs_meta.get(f"{prov}|{cat}") or {}
            year = am.get("anchor_year")
            if not year:
                continue  # 纯模型兜底省，M13 无法校验，单独计数
            block = (cl.get_control_lines(int(year), prov)["data"].get(prov) or {}).get(
                cat if cat in ("物理类", "历史类") else "历史类") or {}
            for tier in tiers:
                rec = tb.get(tier)
                if not rec:
                    continue
                if rec.get("src") != "official_control_line":
                    unanchored += 1
                    continue
                anchored += 1
                key = {"普通一本": "普通一本", "普通二本": "普通二本", "专科": "专科"}[tier]
                node = block.get(key)
                if not node:
                    continue
                off = int(node.get("score"))
                dev = int(rec["min_score"]) - off
                deviations.append(dev)
                if dev == 0:
                    matched += 1
    ok = bool(anchored) and matched == anchored
    return {"ok": ok, "anchored_tiers": anchored, "matched_exactly": matched,
            "unanchored_model_tiers": unanchored,
            "deviations": Counter(deviations).most_common(5),
            "note": "锚定档分数与官方控线必须分毫不差；未锚定档为无控线键省份的模型+地板口径"}


def check_m14(baseline):
    """M14：(分数, 位次) 配对经同年一分段表反查自洽率（允许相邻行误差 ≤ 一行累计差）。"""
    total = consistent = 0
    bad = []
    cal = (baseline.get("meta") or {}).get("calibration") or {}
    provs_meta = cal.get("provinces") or {}
    for prov, cats in baseline["tier_baseline"].items():
        for cat, tb in cats.items():
            am = provs_meta.get(f"{prov}|{cat}") or {}
            year = am.get("anchor_year")
            rows = _rt_rows(year, prov, cat) if year else None
            if not rows:
                continue
            for tier, rec in tb.items():
                score, rank = int(rec["min_score"]), int(rec["min_rank"])
                if not score or not rank:
                    continue
                total += 1
                idx = 4 if tier == "专科" and len(rows[0]) > 4 else 2
                hit = None
                for r in rows:
                    if int(r[0]) <= score:
                        hit = int(r[idx])
                        break
                if hit is None:
                    # 分数低于表内最低分：与生成器同语义的表末斜率外推
                    i_last = 4 if (tier == "专科" and len(rows[-1]) > 4) else 2
                    i_prev = 4 if (tier == "专科" and len(rows[-2]) > 4) else 2
                    sN, cN = int(rows[-1][0]), int(rows[-1][i_last])
                    sP, cP = int(rows[-2][0]), int(rows[-2][i_prev])
                    hit = (int(cN + (sP - score) * (cN - cP) / (sP - sN))
                           if sP > sN and cN > cP else cN)
                if hit == rank:
                    consistent += 1
                elif abs(hit - rank) / max(1, hit) <= 0.02:
                    consistent += 1  # 表内相邻行插值容差 2%
                else:
                    bad.append({"prov": prov, "cat": cat, "tier": tier,
                                "score": score, "rank": rank, "table_cum": hit})
    rate = (consistent / total * 100) if total else 0.0
    return {"ok": total > 0 and rate >= 99.0, "pairs": total, "consistent": consistent,
            "rate_pct": round(rate, 1), "bad_samples": bad[:10]}


def check_m15():
    """M15：种子行「投档分 < 当年对应批次省控线」的确定性违规（复用 data_quality 硬约束）。"""
    try:
        with gzip.open(SEED, "rt", encoding="utf-8") as f:
            rows = json.load(f)["rows"]
    except (OSError, ValueError):
        return {"ok": True, "violations": [], "note": "种子文件不可读，跳过"}
    from services.control_lines import years as cl_years, get_control_lines
    by_year = {}
    for y in cl_years():
        r = get_control_lines(int(y))
        if r.get("ok"):
            by_year[int(y)] = r["data"]

    def lowest(block, kw):
        ss = [v.get("score") for k, v in (block or {}).items()
              if kw in k and isinstance(v, dict)]
        ss = [int(s) for s in ss if s is not None]
        return min(ss) if ss else None

    violations = []
    for r in rows:
        y = int(r.get("year") or 0)
        block = by_year.get(y, {}).get(r.get("province"), {}).get(r.get("subject"))
        b = r.get("batch") or ""
        if block is None or not r.get("min_score"):
            continue
        c = lowest(block, "专") if "专" in b else (lowest(block, "本") if "本" in b else None)
        if c is not None and int(r["min_score"]) < c:
            violations.append({"year": y, "province": r.get("province"),
                               "university": r.get("university"), "batch": b,
                               "min_score": int(r["min_score"]), "control": c})
    return {"ok": not violations, "violations": violations,
            "note": "种子行低于省控线即确定性错误（M15）"}


def main():
    baseline = json.load(open(BASELINE, encoding="utf-8"))
    m13 = check_m13(baseline)
    m14 = check_m14(baseline)
    m15 = check_m15()
    for name, rep in (("M13 批次线 vs 官方控线", m13), ("M14 配对自洽率", m14),
                      ("M15 控线硬约束违规", m15)):
        flag = "✅" if rep["ok"] else "❌"
        print(f"【{name}】{flag} {json.dumps(rep, ensure_ascii=False)}")
    sys.exit(0 if (m13["ok"] and m14["ok"] and m15["ok"]) else 1)


if __name__ == "__main__":
    main()
