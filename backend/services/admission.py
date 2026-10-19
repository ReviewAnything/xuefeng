"""录取数据层（P2 数据侧）。

提供：
  - 参数化样例录取模型（admission_sample.json）
  - 真实数据可插拔：若存在 backend/data/gaokao_advisor.csv 则自动切换为真实记录
  - 给定 (省份, 科类, 专业) 计算各批次录取门槛（最低分/最低位次）
  - 给定用户位次，对某一专业做 冲/稳/保 梯度判定
"""
import csv
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_SAMPLE = os.path.join(_DATA_DIR, "admission_sample.json")
_REAL_CSV = os.path.join(_DATA_DIR, "gaokao_advisor.csv")

# 冲稳保阈值（基于 user_rank / min_rank 比值）
SAFETY_RATIO = 0.85   # < 0.85 保
MATCH_HI = 1.00       # 0.85~1.00 稳
REACH_HI = 1.20       # 1.00~1.20 冲；>1.20 不可及


def _load_sample() -> dict:
    with open(_SAMPLE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_real_rows() -> list:
    """读取真实录取 CSV（若存在）。期望列：province,subject,tier,school,major,min_score,min_rank。"""
    rows = []
    if not os.path.exists(_REAL_CSV):
        return rows
    with open(_REAL_CSV, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "province": r.get("province", "").strip(),
                "subject": r.get("subject", "").strip(),
                "tier": r.get("tier", "").strip(),
                "school": r.get("school", "").strip(),
                "major": r.get("major", "").strip(),
                "min_score": int(r["min_score"]) if r.get("min_score") else None,
                "min_rank": int(r["min_rank"]) if r.get("min_rank") else None,
            })
    return rows


def data_source() -> str:
    return "real" if os.path.exists(_REAL_CSV) else "sample"


def _difficulty(major_cat: str, major_name: str, sample: dict) -> dict:
    overrides = sample.get("major_overrides", {})
    if major_name in overrides:
        return overrides[major_name]
    return sample.get("category_default", {}).get(major_cat, {"score_add": 0, "rank_factor": 1.0})


def major_thresholds(province: str, subject: str, major_name: str, major_cat: str) -> dict:
    """返回某专业在指定省/科类下各批次的录取门槛。"""
    sample = _load_sample()
    baseline = sample["tier_baseline"].get(province, {}).get(subject)
    if not baseline:
        return {"ok": False, "error": f"暂无 {province}/{subject} 的录取基线数据"}
    diff = _difficulty(major_cat, major_name, sample)
    tiers = []
    for tier in sample["tier_order"]:
        base = baseline.get(tier)
        if not base:
            continue
        min_score = base["min_score"] + diff["score_add"]
        min_rank = max(1, round(base["min_rank"] * diff["rank_factor"]))
        tiers.append({"tier": tier, "min_score": min_score, "min_rank": min_rank})
    return {"ok": True, "province": province, "subject": subject, "major": major_name,
            "tiers": tiers, "data_source": data_source()}


def classify(user_rank: int, min_rank: int) -> str:
    """根据用户位次与某批次门槛，判定 冲/稳/保/不可及。"""
    if min_rank <= 0:
        return "不可及"
    ratio = user_rank / min_rank
    if ratio < SAFETY_RATIO:
        return "保"
    if ratio < MATCH_HI:
        return "稳"
    if ratio <= REACH_HI:
        return "冲"
    return "不可及"


def analyze_major(province: str, subject: str, user_rank: int, major_name: str, major_cat: str) -> dict:
    """对某专业做完整的位次可达性分析 + 冲稳保。"""
    th = major_thresholds(province, subject, major_name, major_cat)
    if not th["ok"]:
        return th
    best = None
    for t in th["tiers"]:
        t = dict(t)
        t["level"] = classify(user_rank, t["min_rank"])
        if t["level"] != "不可及":
            # 记录用户能达到的最优（门槛最高/位次最小）批次
            if best is None or t["min_rank"] < best["min_rank"]:
                best = t
    return {
        "ok": True, "province": province, "subject": subject, "major": major_name,
        "user_rank": user_rank, "tiers": th["tiers"], "best_reachable": best,
        "data_source": data_source(),
    }


def search(province: str, subject: str, user_rank: int, limit: int = 20) -> dict:
    """给定用户位次，从非避坑专业中筛选出可达专业并按 冲稳保 组织（数据侧喂给诊断）。"""
    from .content import MAJORS
    sample = _load_sample()
    baseline = sample["tier_baseline"].get(province, {}).get(subject)
    if not baseline:
        return {"ok": False, "error": f"暂无 {province}/{subject} 的录取基线数据"}
    reach, match, safe = [], [], []
    for m in MAJORS:
        if m["view"] == "avoid":
            continue
        th = analyze_major(province, subject, user_rank, m["name"], m["cat"])
        if not th["ok"] or not th["best_reachable"]:
            continue
        item = {"major": m["name"], "cat": m["cat"], "view": m["view"],
                "best_tier": th["best_reachable"]["tier"],
                "best_rank": th["best_reachable"]["min_rank"],
                "best_score": th["best_reachable"]["min_score"],
                "level": th["best_reachable"]["level"]}
        if item["level"] == "冲":
            reach.append(item)
        elif item["level"] == "稳":
            match.append(item)
        else:
            safe.append(item)
    # 排序：同一梯度内按门槛位次升序（越容易越靠前）
    for lst in (reach, match, safe):
        lst.sort(key=lambda x: x["best_rank"])
    return {"ok": True, "province": province, "subject": subject, "user_rank": user_rank,
            "reach": reach[:limit], "match": match[:limit], "safe": safe[:limit],
            "data_source": data_source()}
