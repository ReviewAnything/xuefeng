"""录取数据层（P2 数据侧）。

数据来源优先级：
  1. 数据库（backend/db）：universities / admission_baselines 等表，由 seed 从 JSON 幂等灌入；
     官方值已在播种时合并进同一行，并标注 data_source=official / estimated。
  2. JSON 文件（backend/data/*.json）：数据库不可用时的兜底，保证服务永不因落库失败而中断。

提供：
  - 给定 (省份, 科类, 专业) 计算各批次录取门槛（最低分/最低位次）
  - 给定用户位次，对某一专业做 冲/稳/保 梯度判定
  - 按位次筛选可达专业（数据侧喂给诊断）
  - 全国院校总表检索（2868 所）
"""
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_SAMPLE = os.path.join(_DATA_DIR, "admission_sample.json")
_REAL = os.path.join(_DATA_DIR, "admission_real_baseline.json")
# 11 省官方省控线覆盖层（2024，批次线层级优先于估算基线）
_OFFICIAL = os.path.join(_DATA_DIR, "admission_official_2024.json")

# 冲稳保阈值（基于 user_rank / min_rank 比值）
SAFETY_RATIO = 0.85   # < 0.85 保
MATCH_HI = 1.00       # 0.85~1.00 稳
REACH_HI = 1.20       # 1.00~1.20 冲；>1.20 不可及

# 科类别名归一化：内容侧用「综合/未改革」，基线侧用「综合」
SUBJECT_ALIASES = {"综合/未改革": "综合", "综合类": "综合"}

_BASELINE_CACHE = None
_OFFICIAL_CACHE = None


def _norm_subject(subject: str) -> str:
    return SUBJECT_ALIASES.get(subject, subject)


def _load_baseline() -> dict:
    """优先加载真实基线；不存在时回退到样例。"""
    global _BASELINE_CACHE
    if _BASELINE_CACHE is None:
        path = _REAL if os.path.exists(_REAL) else _SAMPLE
        with open(path, "r", encoding="utf-8") as f:
            _BASELINE_CACHE = json.load(f)
    return _BASELINE_CACHE


def _load_official() -> dict:
    """加载 11 省官方省控线覆盖层（不存在返回空 dict）。"""
    global _OFFICIAL_CACHE
    if _OFFICIAL_CACHE is None:
        if os.path.exists(_OFFICIAL):
            with open(_OFFICIAL, "r", encoding="utf-8") as f:
                _OFFICIAL_CACHE = json.load(f)
        else:
            _OFFICIAL_CACHE = {}
    return _OFFICIAL_CACHE


def _db():
    """返回仓储模块；数据库不可用时返回 None（不抛错）。"""
    try:
        from db import repository as repo
        return repo
    except Exception:
        return None


def invalidate_cache() -> None:
    """同步后调用：清空进程内缓存。"""
    global _BASELINE_CACHE, _OFFICIAL_CACHE
    _BASELINE_CACHE = None
    _OFFICIAL_CACHE = None
    repo = _db()
    if repo:
        try:
            repo.invalidate()
        except Exception:
            pass


def official_coverage() -> list:
    """已接入官方省控线的省份列表。"""
    repo = _db()
    if repo:
        try:
            cov = repo.official_coverage()
            if cov:
                return cov
        except Exception:
            pass
    return _load_official().get("meta", {}).get("coverage", [])


def data_source() -> str:
    """当前实际生效的数据源标签。

    - official_overlay：存在官方省控线覆盖层 + 真实基线（11 省批次线用官方，其余估算）
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


def _tier_order(baseline: dict) -> list:
    repo = _db()
    if repo:
        try:
            order = repo.tier_order()
            if order:
                return order
        except Exception:
            pass
    return baseline.get("tier_order", [])


def _thresholds_from_db(province: str, subject: str):
    repo = _db()
    if not repo:
        return None
    try:
        return repo.thresholds(province, subject)
    except Exception:
        return None


def _thresholds_from_json(province: str, subject: str, diff: dict, baseline: dict) -> list:
    """JSON 兜底：估算基线 + 官方覆盖层。"""
    tiers = baseline["tier_baseline"].get(province, {}).get(subject)
    if not tiers:
        return []
    official = _load_official()
    official_batch = official.get("batch_lines", {}).get(province, {}).get(subject, {})
    official_school = official.get("school_tier_lines", {}).get(province, {}).get(subject, {})
    out = []
    for tier in baseline["tier_order"]:
        base = tiers.get(tier)
        if not base:
            continue
        min_score = base["min_score"] + diff["score_add"]
        min_rank = max(1, round(base["min_rank"] * diff["rank_factor"]))
        src, line, school = "estimated", None, None
        ov = official_batch.get(tier)
        if ov:
            min_score = ov["score"] + diff["score_add"]
            min_rank = max(1, round(ov["rank"] * diff["rank_factor"]))
            src, line = "official", ov.get("line")
        if tier in ("985", "211"):
            sv = official_school.get(tier)
            if sv:
                min_score = sv["score"] + diff["score_add"]
                min_rank = max(1, round(sv["rank"] * diff["rank_factor"]))
                src, line, school = "official", sv.get("line"), sv.get("school")
        out.append({"tier": tier, "min_score": min_score, "min_rank": min_rank,
                    "data_source": src, "line": line, "school": school})
    return out


def major_thresholds(province: str, subject: str, major_name: str, major_cat: str) -> dict:
    """返回某专业在指定省/科类下各批次的录取门槛（含专业难度系数）。

    官方值（11 省省控线 / 985·211 入门投档位次）已在落库时合并，逐层返回 data_source。
    """
    subject = _norm_subject(subject)
    baseline = _load_baseline()
    diff = _difficulty(major_cat, major_name, baseline)

    rows = _thresholds_from_db(province, subject)
    if rows:
        out = []
        for tier in _tier_order(baseline):
            r = rows.get(tier)
            if not r:
                continue
            out.append({
                "tier": tier,
                "min_score": r["min_score"] + diff["score_add"],
                "min_rank": max(1, round(r["min_rank"] * diff["rank_factor"])),
                "data_source": r["data_source"],
                "line": r["line"],
                "school": r["school"],
            })
        if out:
            return {"ok": True, "province": province, "subject": subject, "major": major_name,
                    "tiers": out, "data_source": data_source()}
    else:
        # 数据库无该省数据时，先判断 JSON 是否有（用于错误提示）
        if not baseline["tier_baseline"].get(province, {}).get(subject):
            return {"ok": False, "error": f"暂无 {province}/{subject} 的录取基线数据"}

    out = _thresholds_from_json(province, subject, diff, baseline)
    if not out:
        return {"ok": False, "error": f"暂无 {province}/{subject} 的录取基线数据"}
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


# ---------------------------------------------------------------- 院校

_UNI_CACHE = None
_NAT_CACHE = None


def _load_universities() -> dict:
    """加载 985/211 院校权威清单（JSON 兜底用，缓存）。"""
    global _UNI_CACHE
    if _UNI_CACHE is None:
        with open(os.path.join(_DATA_DIR, "universities.json"), "r", encoding="utf-8") as f:
            _UNI_CACHE = json.load(f)
    return _UNI_CACHE


def _load_national() -> dict:
    """加载全国普通高等学校静态总表（JSON 兜底用，缓存）。"""
    global _NAT_CACHE
    if _NAT_CACHE is None:
        with open(os.path.join(_DATA_DIR, "universities_national.json"), "r", encoding="utf-8") as f:
            _NAT_CACHE = json.load(f)
    return _NAT_CACHE


def universities(province: str = None, tier: str = None, category: str = None,
                 level: str = None, q: str = None, limit: int = 500, offset: int = 0,
                 nature: str = None) -> dict:
    """按条件筛选全国普通高等学校静态总表（教育部官方名单，2868 所）。

    数据库优先；不可用时回落到 JSON。
    """
    repo = _db()
    if repo:
        try:
            return repo.universities(province=province, tier=tier, category=category,
                                     level=level, q=q, nature=nature, limit=limit, offset=offset)
        except Exception:
            pass

    data = _load_national()
    items = data["universities"]
    if province:
        items = [u for u in items if u["province"] == province]
    if level:
        items = [u for u in items if u["level"] == level]
    if tier == "985":
        items = [u for u in items if u["is_985"]]
    elif tier == "211":
        items = [u for u in items if u["is_211"]]
    elif tier == "dfc":
        items = [u for u in items if u["is_dfc"]]
    if category:
        items = [u for u in items if u.get("category") == category]
    if nature:
        items = [u for u in items if u.get("nature") == nature]
    if q:
        q = q.strip()
        items = [u for u in items if q in u["name"]]
    total_matched = len(items)
    offset = max(0, offset)
    items = items[offset:offset + limit]
    meta = data["meta"]
    return {"ok": True, "count": len(items), "total_matched": total_matched,
            "offset": offset, "limit": limit,
            "total": meta["count"], "count_benke": meta["count_benke"],
            "count_zhuanke": meta["count_zhuanke"],
            "count_985": meta["count_985"], "count_211": meta["count_211"],
            "universities": items, "data_source": "static_official_moe"}


def universities_by_tier(tier: str) -> list:
    """返回某层次（985/211）的全部院校名（用于核验页按层次展示可触及院校）。"""
    repo = _db()
    if repo:
        try:
            names = repo.elite_names(tier)
            if names:
                return names
        except Exception:
            pass
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
    subject_n = _norm_subject(subject)
    has_db = _thresholds_from_db(province, subject_n) is not None
    if not has_db and not baseline["tier_baseline"].get(province, {}).get(subject_n):
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
                "level": th["best_reachable"]["level"],
                "data_source": th["best_reachable"].get("data_source", "estimated")}
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
