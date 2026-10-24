#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 gaokao-advisor 参数 + 官方省控线 + 真实一分一段表，生成 xuefeng 录取基线。

数据来源三层（可信度降序）：
1. **官方省控线**（data/admission_control_lines_2022_2026.json，阳光高考逐年主表转录，
   31 省 × 2022-2026）：普通一本/普通二本/专科档阈值直接锚定官方分数（M13 修复——
   旧版一本档中位偏差 -21 分）。
2. **真实一分一段表**（data/rank_tables/*.json，逐年落盘）：所有 (分数, 位次) 配对的
   位次一律由锚定分数经同年一分段表反查生成；985/211 层次（官方无控线）保留模型
   位次门槛、分数改由真实一分段表反查（M14 修复——旧版自洽率仅 10.2%）。
3. **gaokao-advisor 模型参数**（MIT，内置 PROVINCE_SCALE / TIER_PCT / base_seg）：
   仅作位次百分比门槛与无一分段表省份的兜底。

用法：
    python scripts/ingest_gaokao_advisor.py            # 离线生成（内置参数 + 本地数据）
    python scripts/ingest_gaokao_advisor.py --sync     # 先拉取 gaokao-advisor 最新参数
    python scripts/verify_baseline_calibration.py      # 生成后跑 M13/M14/M15 校验

写出 backend/data/admission_real_baseline.json，后端优先使用。
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
CONTROL = os.path.join(BACKEND_DATA, "admission_control_lines_2022_2026.json")
RT_DIR = os.path.join(BACKEND_DATA, "rank_tables")
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
TIER_ORDER = ["985", "211", "普通一本", "普通二本", "专科"]
# 基线科类 -> 一分段表科类键候选（RT.lookup 不做归一，这里自行解析）
RT_SUBJECT_CANDIDATES = {
    "物理类": ["物理类", "物理", "选考物理", "物理科目组合", "理科"],
    "历史类": ["历史类", "历史", "选考历史", "历史科目组合", "文科"],
    "综合": ["综合"],
}
# 基线批次档位 -> 省控线档位键
CL_TIER_KEY = {"普通一本": "普通一本", "普通二本": "普通二本", "专科": "专科"}
YEARS_DESC = [2026, 2025, 2024, 2023, 2022]

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


# ---------------------------------------------------------------- 模型层（保留作兜底）

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
    """纯模型兜底：该省该科类各批次录取门槛（取批次内代表位次 -> 模型表反查分数）。"""
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


# ---------------------------------------------------------------- 校准层（M13/M14）

def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _rank_rows(year, prov, cat):
    """取 (year, prov, cat) 的真实一分段行；返回 (rows, subject_key) 或 (None, None)。

    rows 为 [score, seg, cum]（3 列）或 [score, seg_ben, cum_ben, seg_zhuan, cum_zhuan]（5 列），
    统一整理成 score 降序。科类键按 RT_SUBJECT_CANDIDATES 顺序解析。
    """
    doc = _load_json(os.path.join(RT_DIR, str(year), f"{prov}.json"))
    if not doc:
        return None, None
    subs = doc.get("subjects") or {}
    for key in RT_SUBJECT_CANDIDATES.get(cat, []):
        blk = subs.get(key)
        if blk and blk.get("rows"):
            rows = sorted(blk["rows"], key=lambda r: -int(r[0]))
            return rows, key
    return None, None


def _cl_block(control, year, prov, cat):
    """取官方省控线 (year, prov, cat) 的档位块；综改省（综合科类）要求历史/物理双键同值。

    返回 {档位键: score} 或 None。双写校验：两键同档位分值必须一致，不一致不臆造。
    """
    blk = ((control.get("by_year") or {}).get(str(year)) or {}).get("batch_lines", {})
    if cat in ("物理类", "历史类"):
        block = blk.get(prov, {}).get(cat)
        if not block:
            return None
        return {k: int(v.get("score")) for k, v in block.items()
                if isinstance(v, dict) and v.get("score") is not None}
    # 综合：双键同值才可用
    hist = blk.get(prov, {}).get("历史类") or {}
    phys = blk.get(prov, {}).get("物理类") or {}
    if not hist or not phys:
        return None
    merged = {}
    for k in set(hist) | set(phys):
        hs = (hist.get(k) or {}).get("score")
        ps = (phys.get(k) or {}).get("score")
        if hs is None or ps is None or int(hs) != int(ps):
            return None  # 双写不一致 → 放弃锚定，不臆造
        merged[k] = int(hs)
    return merged


def score_from_rank(rows, rk, zhuan: bool = False):
    """位次 -> 分数（真实一分段表；本科档用 r[2]，专科档 5 列表用 r[4]、3 列表回退 r[2]）。"""
    idx = 4 if zhuan else 2
    pts = sorted(((int(r[idx]), int(r[0])) for r in rows
                  if len(r) > idx and int(r[idx]) > 0),
                 key=lambda x: x[0])
    if not pts:
        if zhuan:
            return score_from_rank(rows, rk, zhuan=False)
        return None
    if rk <= pts[0][0]:
        if len(pts) >= 2 and pts[1][0] != pts[0][0]:
            sc = pts[0][1] + (pts[1][1] - pts[0][1]) * (rk - pts[0][0]) / (pts[1][0] - pts[0][0])
            return int(min(750, max(pts[0][1], sc)))
        return pts[0][1]
    if rk >= pts[-1][0]:
        sN, cN = pts[-1]
        sP, cP = pts[-2] if len(pts) >= 2 else (sN, max(1, cN - 1))
        if cN != cP:
            sc = sN - (sN - 150) * (rk - cN) / max(1, int(cN * 0.2))
            return max(150, int(sc))
        return max(150, sN - 20)
    lower = None
    for cum, sc in pts:
        if cum >= rk:
            if lower is None:
                return sc
            ratio = (rk - lower[0]) / (cum - lower[0]) if cum != lower[0] else 0
            return int(lower[1] + (sc - lower[1]) * ratio)
        lower = (cum, sc)
    return pts[-1][1]


def rank_from_score(rows, score, zhuan: bool = False):
    """分数 -> 位次（与 services/rank_tables.lookup 同语义：取不高于该分的最近行）。

    双档表专科档取 r[4]，单档表回退 r[2]；分数低于表内最低分（超出覆盖下限）时
    按表末两点斜率外推——低于表覆盖下限的位次区分度无表可依，线性外推可保
    「分数越低位次越大」严格成立（专科线常低于一分段表下限）。
    """
    idx_ben, idx_zh = 2, 4
    for r in rows:
        if int(r[0]) <= score:
            i = idx_zh if (zhuan and len(r) > idx_zh) else idx_ben
            return int(r[i])
    # 低于表内最低分：外推
    i_last = idx_zh if (zhuan and len(rows[-1]) > idx_zh) else idx_ben
    i_prev = idx_zh if (zhuan and len(rows[-2]) > idx_zh) else idx_ben
    sN, cN = int(rows[-1][0]), int(rows[-1][i_last])
    sP, cP = int(rows[-2][0]), int(rows[-2][i_prev])
    if len(rows) >= 2 and sP > sN and cN > cP:
        return int(cN + (sP - score) * (cN - cP) / (sP - sN))
    return cN


def calibrate_tiers(prov, cat, total, control):
    """官方控线锚定 + 真实一分段表反查，产出该 (省, 科类) 五档门槛。

    返回 ({tier: {min_score, min_rank, src}}, anchor_year, rt_key) ；无一分段表时 (None, None, None)。
    src 取值：official_control_line / rank_table_model_rank。
    """
    rows = rt_key = None
    anchor_year = None
    for y in YEARS_DESC:
        rows, rt_key = _rank_rows(y, prov, cat)
        if rows:
            anchor_year = y
            break
    if not rows:
        return None, None, None
    cl = _cl_block(control, anchor_year, prov, cat) or {}

    def pct_for(tier):
        if tier == "985":
            return TIER_PCT["985_mid"]
        if tier == "211":
            return TIER_PCT["211_mid"]
        if tier == "普通一本":
            p = TIER_PCT[DEFAULT_BUCKET["双一流"]]
        elif tier == "普通二本":
            p = TIER_PCT[DEFAULT_BUCKET["普通"]]
        else:
            return 0.95
        if "历史" in cat:
            p = min(p * 0.7 + 0.05, 0.95)
        return p

    # 1) 目标分数：官方控线优先，否则模型位次经真实一分段表反查
    target = {}
    for tier in TIER_ORDER:
        if tier in ("普通一本", "普通二本", "专科") and tier in cl:
            target[tier] = {"score": int(cl[tier]), "src": "official_control_line"}
        else:
            base_rank = max(1, int(total * pct_for(tier)))
            sc = score_from_rank(rows, base_rank, zhuan=(tier == "专科"))
            if tier == "专科":
                # 无官方专科线的省份（如上海）：一分段表终端即本科批线，0.95 分位会
                # 落在本科线上、与二本档并列——专科门槛语义上必须低于本科地板，
                # 取 min(模型分, 本科地板-1)，位次随后由表末斜率外推。
                ben_floor = cl.get("普通二本") or cl.get("普通一本")
                if ben_floor:
                    sc = min(sc, int(ben_floor) - 1)
                sc = max(sc, 150)
            if sc is None:
                return None, None, None
            target[tier] = {"score": int(sc), "src": "rank_table_model_rank"}

    # 2) 兜底地板：合并批次省无一本线时，一本档不得低于本科线（官方地板）
    floor = cl.get("普通二本") or cl.get("普通一本")
    if floor and target["普通一本"]["src"] != "official_control_line":
        target["普通一本"]["score"] = max(target["普通一本"]["score"], int(floor))
    if floor and target["普通二本"]["src"] != "official_control_line":
        target["普通二本"]["score"] = max(target["普通二本"]["score"], int(floor))

    # 3) 单调化（自下而上）：官方锚定值不动，模型档低于官方低档时抬升
    #    （211 模型分低于一本线 = 模型百分比在该省失真，抬到官方地板并随后重查位次）。
    order_bottom_up = ["专科", "普通二本", "普通一本", "211", "985"]
    for lo_t, hi_t in zip(order_bottom_up, order_bottom_up[1:]):
        if target[hi_t]["score"] < target[lo_t]["score"]:
            if target[hi_t]["src"] != "official_control_line":
                target[hi_t]["score"] = target[lo_t]["score"]
            elif target[lo_t]["src"] != "official_control_line":
                target[lo_t]["score"] = target[hi_t]["score"]
            # 两者均为官方锚定却倒挂：数据问题，保持原值交由校验器暴露

    # 4) 位次一律由最终分数经同年一分段表反查（M14：配对自洽）
    out = {}
    for tier in TIER_ORDER:
        score = target[tier]["score"]
        rank = rank_from_score(rows, score, zhuan=(tier == "专科"))
        if rank is None:
            rank = max(1, int(total * pct_for(tier)))  # 极端兜底（表为空时已在上面拦截）
        out[tier] = {"min_score": score, "min_rank": rank, "src": target[tier]["src"]}
    return out, anchor_year, rt_key


# ---------------------------------------------------------------- 主流程

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
    ap = argparse.ArgumentParser(description="生成 xuefeng 录取基线（官方控线锚定 + 一分段表反查）")
    ap.add_argument("--sync", action="store_true", help="先拉取 gaokao-advisor 最新参数")
    args = ap.parse_args()

    global PROVINCE_SCALE, TIER_PCT, base_seg
    if args.sync:
        p = sync_params()
        PROVINCE_SCALE, TIER_PCT, base_seg = p["PROVINCE_SCALE"], p["TIER_PCT"], p["base_seg"]
        print("[sync] 已更新参数：", list(p.keys()))

    control = _load_json(CONTROL) or {}
    seg = build_segments()
    sample = json.load(open(SAMPLE, encoding="utf-8"))

    tier_baseline = {}
    calibration = {"provinces": {}, "totals": {"official_control_line": 0,
                                               "rank_table_model_rank": 0,
                                               "model_fallback": 0}}
    for prov, cats in PROVINCE_SCALE.items():
        for cat, total in cats.items():
            calibrated, anchor_year, rt_key = calibrate_tiers(prov, cat, total, control)
            if calibrated:
                tier_baseline.setdefault(prov, {})[cat] = calibrated
                calibration["provinces"][f"{prov}|{cat}"] = {
                    "anchor_year": anchor_year,
                    "rank_table_subject": rt_key,
                }
                for t in calibrated.values():
                    calibration["totals"][t["src"]] = calibration["totals"].get(t["src"], 0) + 1
            else:
                # 无一分段表：纯模型兜底（旧口径），并在校准账目中如实计数
                tier_baseline.setdefault(prov, {})[cat] = tier_baseline_for(prov, cat, total, seg)
                for t in tier_baseline[prov][cat].values():
                    calibration["totals"]["model_fallback"] = \
                        calibration["totals"].get("model_fallback", 0) + 1

    out = {
        "meta": {
            "year": 2026,
            "source": "gaokao-advisor + official control lines + rank tables",
            "note": ("由 scripts/ingest_gaokao_advisor.py 生成：普通一本/普通二本/专科档阈值锚定"
                     "官方省控线（admission_control_lines_2022_2026.json，M13）；全部 (分数,位次) "
                     "配对的位次由同年真实一分一段表反查（data/rank_tables，M14）；985/211 层次"
                     "保留模型位次百分比门槛、分数经真实一分段表反查。无一分段表数据的省份回退"
                     "gaokao-advisor 模型口径（meta.calibration.totals.model_fallback 可查）。"
                     "专科为估算值。后端优先使用本文件，仅供学习参考。"),
            "calibration": calibration,
        },
        "tier_order": TIER_ORDER,
        "tier_baseline": tier_baseline,
        "category_default": sample.get("category_default", {}),
        "major_overrides": sample.get("major_overrides", {}),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[ok] 已写出 {OUT}")
    print(f"     省份数：{len(tier_baseline)}")
    print(f"     校准账目：{calibration['totals']}")
    demo = tier_baseline.get("河南", {}).get("物理类", {})
    print("     河南/物理类 样例：", {k: {kk: vv for kk, vv in v.items() if kk != 'src'}
                                  for k, v in demo.items()})


if __name__ == "__main__":
    main()
