#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 chenxuyaun/gaokao-advisor 生成 xuefeng 真实录取基线。

gaokao-advisor（MIT）用「31 省 2026 一分一段表 + 283 所大学 + 院校层次」通过确定性公式
生成各省各批次录取位次。本脚本复用其权威参数（base_seg / PROVINCE_SCALE / TIER_PCT），
计算 xuefeng 所需的 per-(省份, 科类, 批次) 录取门槛，写出
backend/data/admission_real_baseline.json（结构与 admission_sample.json 一致，
后端优先使用，自动覆盖 31 省真实基线）。

用法：
    python scripts/ingest_gaokao_advisor.py            # 用内置参数生成（离线）
    python scripts/ingest_gaokao_advisor.py --sync     # 拉取 gaokao-advisor 最新参数后生成

数据来源：https://github.com/chenxuyaun/gaokao-advisor  (MIT License)
"""
import argparse
import ast
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DATA = os.path.join(HERE, "..", "data")
SAMPLE = os.path.join(BACKEND_DATA, "admission_sample.json")
OUT = os.path.join(BACKEND_DATA, "admission_real_baseline.json")
GA_REPO = "https://github.com/chenxuyaun/gaokao-advisor.git"

# ===== 内置参数（来自 gaokao-advisor data/seed_unified.py，MIT）=====
PROVINCE_SCALE = {
    "广东": {"物理类": 350000, "历史类": 120000}, "河南": {"物理类": 420000, "历史类": 150000},
    "江苏": {"物理类": 280000, "历史类": 100000}, "山东": {"综合": 450000},
    "湖北": {"物理类": 220000, "历史类": 80000}, "浙江": {"综合": 290000},
    "湖南": {"物理类": 300000, "历史类": 110000}, "河北": {"物理类": 320000, "历史类": 120000},
    "安徽": {"物理类": 250000, "历史类": 90000}, "四川": {"物理类": 300000, "历史类": 110000},
    "福建": {"物理类": 180000, "历史类": 70000}, "江西": {"物理类": 200000, "历史类": 75000},
    "陕西": {"物理类": 150000, "历史类": 55000}, "山西": {"物理类": 160000, "历史类": 60000},
    "辽宁": {"物理类": 130000, "历史类": 50000}, "重庆": {"物理类": 115000, "历史类": 45000},
    "贵州": {"物理类": 220000, "历史类": 80000}, "云南": {"物理类": 180000, "历史类": 70000},
    "黑龙江": {"物理类": 110000, "历史类": 40000}, "吉林": {"物理类": 90000, "历史类": 35000},
    "甘肃": {"物理类": 120000, "历史类": 45000}, "广西": {"物理类": 200000, "历史类": 75000},
    "内蒙古": {"物理类": 80000, "历史类": 30000}, "新疆": {"物理类": 85000, "历史类": 35000},
    "北京": {"综合": 55000}, "天津": {"综合": 55000}, "上海": {"综合": 52000}, "海南": {"综合": 40000},
    "宁夏": {"物理类": 55000, "历史类": 25000}, "青海": {"物理类": 31000, "历史类": 16000},
    "西藏": {"物理类": 20000, "历史类": 14000},
}
TIER_PCT = {"985_top": 0.003, "985_mid": 0.02, "985_low": 0.06, "211_top": 0.12,
            "211_mid": 0.25, "211_low": 0.40, "双一流": 0.50, "普通_good": 0.65,
            "普通_mid": 0.80, "普通_low": 0.95}
# 院校层次 -> 百分比桶（与 gaokao-advisor DEFAULT_BUCKET 一致）
DEFAULT_BUCKET = {"985": "985_mid", "211": "211_mid", "双一流": "211_low", "普通": "普通_mid"}
# 院校层次 -> xuefeng 批次
LEVEL_TO_TIER = {"985": "985", "211": "211", "双一流": "普通一本", "普通": "普通二本"}
base_seg = {
    "北京": [("综合", 521, 22000), ("综合", 429, 45000), ("综合", 400, 55000)],
    "天津": [("综合", 547, 18000), ("综合", 458, 42000), ("综合", 400, 55000)],
    "上海": [("综合", 504, 16000), ("综合", 403, 42000), ("综合", 350, 52000)],
    "浙江": [("综合", 594, 58000), ("综合", 494, 170000), ("综合", 450, 200000)],
    "山东": [("综合", 525, 130000), ("综合", 442, 310000), ("综合", 400, 350000)],
    "海南": [("综合", 568, 12000), ("综合", 479, 28000), ("综合", 400, 40000)],
    "广东": [("物理类", 539, 85000), ("物理类", 425, 260000), ("物理类", 400, 280000),
             ("历史类", 546, 22000), ("历史类", 440, 90000), ("历史类", 400, 105000)],
    "河南": [("物理类", 513, 125000), ("物理类", 419, 310000), ("物理类", 400, 330000),
             ("历史类", 534, 26000), ("历史类", 459, 90000), ("历史类", 400, 115000)],
    "江苏": [("物理类", 513, 80000), ("物理类", 456, 180000), ("物理类", 400, 210000),
             ("历史类", 532, 22000), ("历史类", 484, 65000), ("历史类", 400, 90000)],
    "湖北": [("物理类", 529, 60000), ("物理类", 435, 180000), ("物理类", 400, 210000),
             ("历史类", 532, 15000), ("历史类", 443, 60000), ("历史类", 400, 75000)],
    "湖南": [("物理类", 481, 100000), ("物理类", 400, 240000), ("物理类", 380, 260000),
             ("历史类", 494, 25000), ("历史类", 446, 70000), ("历史类", 400, 92000)],
    "河北": [("物理类", 510, 100000), ("物理类", 443, 220000), ("物理类", 400, 250000),
             ("历史类", 542, 25000), ("历史类", 485, 70000), ("历史类", 400, 100000)],
    "安徽": [("物理类", 514, 70000), ("物理类", 451, 160000), ("物理类", 400, 190000),
             ("历史类", 522, 18000), ("历史类", 490, 45000), ("历史类", 400, 70000)],
    "福建": [("物理类", 528, 45000), ("物理类", 446, 110000), ("物理类", 400, 135000),
             ("历史类", 533, 10000), ("历史类", 458, 35000), ("历史类", 400, 47000)],
    "江西": [("物理类", 505, 60000), ("物理类", 412, 180000), ("物理类", 400, 190000),
             ("历史类", 535, 15000), ("历史类", 479, 50000), ("历史类", 400, 72000)],
    "辽宁": [("物理类", 508, 48000), ("物理类", 344, 120000), ("物理类", 300, 130000),
             ("历史类", 527, 12000), ("历史类", 442, 35000), ("历史类", 300, 58000)],
    "重庆": [("物理类", 496, 45000), ("物理类", 406, 110000), ("物理类", 350, 130000),
             ("历史类", 510, 12000), ("历史类", 415, 40000), ("历史类", 350, 52000)],
    "陕西": [("物理类", 451, 60000), ("物理类", 376, 130000), ("物理类", 350, 145000),
             ("历史类", 462, 15000), ("历史类", 385, 45000), ("历史类", 350, 54000)],
    "黑龙江": [("物理类", 464, 35000), ("物理类", 340, 100000), ("物理类", 300, 115000),
               ("历史类", 466, 9000), ("历史类", 385, 35000), ("历史类", 300, 45000)],
    "吉林": [("物理类", 473, 25000), ("物理类", 321, 80000), ("物理类", 300, 89000),
             ("历史类", 478, 6500), ("历史类", 343, 30000), ("历史类", 300, 36000)],
    "甘肃": [("物理类", 477, 35000), ("物理类", 367, 95000), ("物理类", 350, 102000),
             ("历史类", 508, 9000), ("历史类", 405, 40000), ("历史类", 350, 50000)],
    "内蒙古": [("物理类", 488, 25000), ("物理类", 363, 70000), ("物理类", 350, 76000),
               ("历史类", 512, 6500), ("历史类", 403, 23000), ("历史类", 350, 29000)],
    "新疆": [("物理类", 468, 18000), ("物理类", 304, 70000), ("物理类", 250, 85000),
             ("历史类", 451, 6500), ("历史类", 315, 32000), ("历史类", 250, 42000)],
    "宁夏": [("物理类", 437, 15000), ("物理类", 360, 45000), ("物理类", 300, 55000),
             ("历史类", 474, 5000), ("历史类", 393, 18000), ("历史类", 300, 25000)],
    "青海": [("物理类", 417, 8000), ("物理类", 344, 25000), ("物理类", 300, 31000),
             ("历史类", 427, 3500), ("历史类", 376, 12000), ("历史类", 300, 16000)],
    "西藏": [("物理类", 400, 5000), ("物理类", 300, 15000), ("物理类", 250, 20000),
             ("历史类", 400, 3000), ("历史类", 304, 10000), ("历史类", 250, 14000)],
    "云南": [("物理类", 505, 50000), ("物理类", 435, 110000), ("物理类", 400, 125000),
             ("历史类", 545, 12000), ("历史类", 465, 42000), ("历史类", 400, 55000)],
    "贵州": [("物理类", 494, 45000), ("物理类", 393, 150000), ("物理类", 350, 170000),
             ("历史类", 503, 15000), ("历史类", 439, 55000), ("历史类", 350, 75000)],
    "广西": [("物理类", 510, 45000), ("物理类", 368, 150000), ("物理类", 350, 160000),
             ("历史类", 520, 12000), ("历史类", 398, 55000), ("历史类", 350, 68000)],
    "山西": [("物理类", 524, 30000), ("物理类", 401, 100000), ("物理类", 350, 120000),
             ("历史类", 538, 7000), ("历史类", 409, 38000), ("历史类", 350, 48000)],
    "四川": [("物理类", 519, 100000), ("物理类", 435, 200000), ("物理类", 400, 220000),
             ("物理类", 686, 54), ("物理类", 600, 22303), ("物理类", 595, 26200),
             ("物理类", 594, 26800), ("物理类", 593, 27400), ("物理类", 592, 28000),
             ("物理类", 591, 28600), ("物理类", 590, 29671), ("物理类", 585, 33000),
             ("物理类", 580, 38064), ("物理类", 570, 47472), ("物理类", 560, 57965),
             ("物理类", 550, 69422), ("历史类", 525, 30000), ("历史类", 455, 80000),
             ("历史类", 400, 105000)],
}


def build_segments():
    """由 base_seg 生成各省各科类的一分一段表（含插值点），与 gaokao-advisor 一致。"""
    seg = {}
    for prov, entries in base_seg.items():
        by_cat = {}
        for cat, score, cum in entries:
            by_cat.setdefault(cat, []).append((score, cum))
        for cat, points in by_cat.items():
            points.sort()
            for score, cum in points:
                seg.setdefault(prov, {}).setdefault(cat, []).append((score, cum))
            for i in range(len(points) - 1):
                lo_s, lo_r = points[i]
                hi_s, hi_r = points[i + 1]
                step = (hi_s - lo_s) // 5
                if step < 2:
                    continue
                for j in range(1, 5):
                    mid_s = lo_s + step * j
                    mid_r = int(lo_r + (hi_r - lo_r) * (mid_s - lo_s) / (hi_s - lo_s))
                    seg[prov][cat].append((mid_s, mid_r))
            # 必须按「累计人数(位次)」升序，rank_to_score 才能正确插值
            seg[prov][cat].sort(key=lambda x: x[1])
    return seg


def rank_to_score(seg, prov, cat, rk):
    """由位次反查分数：区间内线性插值；区间外按顶部/末端两点斜率外推（封顶 750 / 下限 150）。"""
    rows = seg.get(prov, {}).get(cat, [])
    if not rows:
        return 400
    if rk <= rows[0][1]:
        # 高于最优锚点（更靠前）：用顶部两点斜率外推，避免钳到最低分
        if len(rows) >= 2:
            s0, c0 = rows[0]
            s1, c1 = rows[1]
            if c1 != c0:
                sc = s0 + (s1 - s0) * (rk - c0) / (c1 - c0)
                return int(min(750, max(s0, sc)))
        return rows[0][0]
    if rk >= rows[-1][1]:
        # 低于最差锚点：向 150 分收敛
        sN, cN = rows[-1]
        return max(150, int(sN - (sN - 150) * (rk - cN) / max(1, int(cN * 0.2))))
    lower = None
    for sc, cum in rows:
        if cum >= rk:
            if lower is None:
                return sc
            ratio = (rk - lower[1]) / (cum - lower[1]) if cum != lower[1] else 0
            return int(lower[0] + (sc - lower[0]) * ratio)
        lower = (sc, cum)
    return rows[-1][0]


def tier_baseline_for(prov, cat, total, seg):
    """计算该省该科类的各批次录取门槛（取批次内代表位次 -> 反查分数）。"""
    out = {}
    for level, tier in LEVEL_TO_TIER.items():
        pct = TIER_PCT[DEFAULT_BUCKET[level]]
        if "历史" in cat:
            pct = min(pct * 0.7 + 0.05, 0.95)
        base_rank = max(1, int(total * pct))
        out[tier] = {"min_score": rank_to_score(seg, prov, cat, base_rank),
                     "min_rank": base_rank}
    # 专科：估算（gaokao-advisor 仅含本科院校，无专科层次）
    zhuan_rank = round(total * 0.95)
    out["专科"] = {"min_score": 200, "min_rank": zhuan_rank}
    return out


def sync_params():
    """拉取 gaokao-advisor 最新参数（ast 解析，安全不执行）。"""
    cache = os.path.join(HERE, "..", "..", ".cache", "gaokao-advisor")
    if not os.path.isdir(os.path.join(cache, "data")):
        subprocess.run(["git", "clone", "--depth", "1", GA_REPO, cache], check=True)
    src = os.path.join(cache, "data", "seed_unified.py")
    tree = ast.parse(open(src, encoding="utf-8").read())
    params = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ("PROVINCE_SCALE", "TIER_PCT", "base_seg"):
                    params[t.id] = ast.literal_eval(node.value)
    return params


def main():
    ap = argparse.ArgumentParser(description="生成 xuefeng 真实录取基线（基于 gaokao-advisor）")
    ap.add_argument("--sync", action="store_true", help="先拉取 gaokao-advisor 最新参数")
    args = ap.parse_args()

    global PROVINCE_SCALE, TIER_PCT, base_seg
    if args.sync:
        p = sync_params()
        PROVINCE_SCALE, TIER_PCT, base_seg = p["PROVINCE_SCALE"], p["TIER_PCT"], p["base_seg"]
        print("[sync] 已更新参数：", list(p.keys()))

    seg = build_segments()
    sample = json.load(open(SAMPLE, encoding="utf-8"))

    tier_baseline = {}
    for prov, cats in PROVINCE_SCALE.items():
        for cat, total in cats.items():
            tier_baseline.setdefault(prov, {})[cat] = tier_baseline_for(prov, cat, total, seg)

    out = {
        "meta": {
            "year": 2026,
            "source": "gaokao-advisor",
            "note": ("由 scripts/ingest_gaokao_advisor.py 基于 chenxuyaun/gaokao-advisor（MIT）的 "
                     "31 省一分一段表/院校层次参数生成，覆盖 31 省。位次门槛为模型推算；分数在锚点区间内插值、"
                     "区间外按斜率外推（顶尖/末端为估算）。专科为估算值。后端优先使用本文件，仅供学习参考。"),
        },
        "tier_order": ["985", "211", "普通一本", "普通二本", "专科"],
        "tier_baseline": tier_baseline,
        "category_default": sample.get("category_default", {}),
        "major_overrides": sample.get("major_overrides", {}),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[ok] 已写出 {OUT}")
    print(f"     省份数：{len(tier_baseline)}")
    demo = tier_baseline.get("河南", {}).get("物理类", {})
    print("     河南/物理类 样例：", demo)
    hn = tier_baseline.get("河南", {}).get("历史类", {})
    print("     河南/历史类 样例：", hn)


if __name__ == "__main__":
    main()
