"""录取数据层（P2 数据侧）。

数据来源（按优先级，结构一致：{ meta, tier_order, tier_baseline, category_default, major_overrides }）：
  - backend/data/admission_real_baseline.json  （由 scripts/ingest_gaokao_advisor.py 从
    chenxuyaun/gaokao-advisor 的真实一分一段表/院校层次生成，覆盖 31 省；存在时自动启用）
  - backend/data/admission_sample.json         （参数化样例，fallback / 演示用）

提供：
  - 给定 (省份, 科类, 专业) 计算各批次录取门槛（最低分/最低位次）
  - 给定用户位次，对某一专业做 冲/稳/保 梯度判定
  - 按位次筛选可达专业（数据侧喂给诊断）
"""
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_SAMPLE = os.path.join(_DATA_DIR, "admission_sample.json")
_REAL = os.path.join(_DATA_DIR, "admission_real_baseline.json")
# 6 省官方省控线覆盖层（2024，批次线层级优先于估算基线）
_OFFICIAL = os.path.join(_DATA_DIR, "admission_official_2024.json")

# 冲稳保阈值（基于 user_rank / min_rank 比值）
SAFETY_RATIO = 0.85   # < 0.85 保
MATCH_HI = 1.00       # 0.85~1.00 稳
REACH_HI = 1.20       # 1.00~1.20 冲；>1.20 不可及

# 科类别名归一化：内容侧用「综合/未改革」，基线侧用「综合」
SUBJECT_ALIASES = {"综合/未改革": "综合", "综合类": "综合"}


def _norm_subject(subject: str) -> str:
    return SUBJECT_ALIASES.get(subject, subject)


def _load_baseline() -> dict:
    """优先加载真实基线；不存在时回退到样例。"""
    path = _REAL if os.path.exists(_REAL) else _SAMPLE
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_official() -> dict:
    """加载 6 省官方省控线覆盖层（不存在返回空 dict）。"""
    if os.path.exists(_OFFICIAL):
        with open(_OFFICIAL, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def official_coverage() -> list:
    """已接入官方省控线的省份列表。"""
    return _load_official().get("meta", {}).get("coverage", [])


def data_source() -> str:
    """当前实际生效的数据源标签。

    - official_overlay：存在官方省控线覆盖层 + 真实基线（6 省批次线用官方，其余估算）
    - real：仅真实估算基线
    - sample：仅参数化样例
    """
    has_real = os.path.exists(_REAL)
    has_official = os.path.exists(_OFFICIAL)
    if has_official and has_real:
        return "official_overlay"
    if has_real:
        return "real"
    return "sample"


def _difficulty(major_cat: str, major_name: str, baseline: dict) -> dict:
    overrides = baseline.get("major_overrides", {})
    if major_name in overrides:
        return overrides[major_name]
    return baseline.get("category_default", {}).get(major_cat, {"score_add": 0, "rank_factor": 1.0})


def major_thresholds(province: str, subject: str, major_name: str, major_cat: str) -> dict:
    """返回某专业在指定省/科类下各批次的录取门槛（含专业难度系数）。

    批次线层级（普通一本/普通二本/专科）若命中官方省控线覆盖层，优先用官方
    score/rank 并标注 data_source=official；985/211 为学校层级，官方无对应省控线，
    维持估算基线并标注 estimated。
    """
    subject = _norm_subject(subject)
    baseline = _load_baseline()
    tiers = baseline["tier_baseline"].get(province, {}).get(subject)
    if not tiers:
        return {"ok": False, "error": f"暂无 {province}/{subject} 的录取基线数据"}
    diff = _difficulty(major_cat, major_name, baseline)
    official = _load_official().get("batch_lines", {}).get(province, {}).get(subject, {})
    out = []
    for tier in baseline["tier_order"]:
        base = tiers.get(tier)
        if not base:
            continue
        # 默认：估算基线
        min_score = base["min_score"] + diff["score_add"]
        min_rank = max(1, round(base["min_rank"] * diff["rank_factor"]))
        src = "estimated"
        line = None
        # 官方覆盖：批次线优先
        ov = official.get(tier)
        if ov:
            min_score = ov["score"] + diff["score_add"]
            min_rank = max(1, round(ov["rank"] * diff["rank_factor"]))
            src = "official"
            line = ov.get("line")
        out.append({"tier": tier, "min_score": min_score, "min_rank": min_rank,
                    "data_source": src, "line": line})
    return {"ok": True, "province": province, "subject": subject, "major": major_name,
            "tiers": out, "data_source": data_source()}


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
    if not isinstance(user_rank, int) or user_rank <= 0:
        return {"ok": False, "error": "位次必须为正整数"}
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


_UNI_CACHE = None


def _load_universities() -> dict:
    """加载 985/211 院校完整静态清单（缓存）。"""
    global _UNI_CACHE
    if _UNI_CACHE is None:
        path = os.path.join(_DATA_DIR, "universities.json")
        with open(path, "r", encoding="utf-8") as f:
            _UNI_CACHE = json.load(f)
    return _UNI_CACHE


def universities(province: str = None, tier: str = None, category: str = None,
                 q: str = None, limit: int = 300) -> dict:
    """按条件筛选 985/211 院校完整静态清单（教育部官方名单，112 所）。

    tier: "985" 仅返回 985（39 所）；"211" 返回全部 211（112 所，含 985）。
    q: 校名/简称模糊匹配。
    """
    data = _load_universities()
    items = data["universities"]
    if province:
        items = [u for u in items if u["province"] == province]
    if tier == "985":
        items = [u for u in items if u["is_985"]]
    elif tier == "211":
        items = [u for u in items if u["is_211"]]
    if category:
        items = [u for u in items if u["category"] == category]
    if q:
        q = q.strip()
        items = [u for u in items if q in u["name"] or q in u["short"]]
    items = items[:limit]
    return {"ok": True, "count": len(items), "total": data["meta"]["count"],
            "count_985": data["meta"]["count_985"],
            "universities": items, "data_source": "static_official"}


def universities_by_tier(tier: str) -> list:
    """返回某层次（985/211）的全部院校名（用于核验页按层次展示可触及院校）。"""
    data = _load_universities()
    if tier == "985":
        return [u["name"] for u in data["universities"] if u["is_985"]]
    if tier == "211":
        return [u["name"] for u in data["universities"] if u["is_211"]]
    return []


def analyze_major(province: str, subject: str, user_rank: int, major_name: str, major_cat: str) -> dict:
    """对某专业做完整的位次可达性分析 + 冲稳保，并附带可触及层次的院校清单。"""
    if not isinstance(user_rank, int) or user_rank <= 0:
        return {"ok": False, "error": "位次必须为正整数"}
    th = major_thresholds(province, subject, major_name, major_cat)
    if not th["ok"]:
        return th
    best = None
    for t in th["tiers"]:
        t = dict(t)
        t["level"] = classify(user_rank, t["min_rank"])
        if t["level"] != "不可及":
            if best is None or t["min_rank"] < best["min_rank"]:
                best = t
    reachable_schools = universities_by_tier(best["tier"]) if best else []
    return {
        "ok": True, "province": province, "subject": subject, "major": major_name,
        "user_rank": user_rank, "tiers": th["tiers"], "best_reachable": best,
        "reachable_tier": best["tier"] if best else None,
        "reachable_tier_schools": reachable_schools,
        "reachable_tier_school_count": len(reachable_schools),
        "data_source": data_source(),
    }


def search(province: str, subject: str, user_rank: int, limit: int = 20) -> dict:
    """给定用户位次，从非避坑专业中筛选出可达专业并按 冲稳保 组织（数据侧喂给诊断）。"""
    from .content import MAJORS

    if not isinstance(user_rank, int) or user_rank <= 0:
        return {"ok": False, "error": "位次必须为正整数"}
    baseline = _load_baseline()
    tiers = baseline["tier_baseline"].get(province, {}).get(_norm_subject(subject))
    if not tiers:
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
