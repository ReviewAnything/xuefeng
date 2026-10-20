"""等位分换算（C2）：把某省/某科类/某年的分数或位次，换算到另一年的等效分数与位次。

为什么需要它
------------
同一所院校在不同年份的录取「分数」不可直接比较（题目难度、批次合并都会让分数漂移），
但「位次」与「位次百分位」相对稳定。因此换算链路固定为：

    分数 --(本省本年曲线)--> 位次 --(目标年曲线)--> 等效分数

锚点来源（按优先级）
--------------------
1. ``backend/data/score_tables.json``（可选）：真实一分一段表，形如
   ``{省份: {科类: {年份: {"cohort_size": 总人数, "points": [[score, rank], ...]}}}}``
   谁有官方数据就往里填，无需改代码即可覆盖下面所有估算锚点。
2. ``admission_official_2024.json``：11 省官方省控线 + 985/211 入门投档位次（2024）。
3. ``admission_real_baseline.json`` / ``admission_sample.json``：31 省估算/样例基线
   （年份取自各自 meta.year）。

换算方法
--------
- ``rank``（默认）：同一位次在目标年锚点曲线上插值 —— 市面主流「同位次等效分」口径。
- ``percentile``：先把位次转成百分位（rank / cohort_size），再在目标年按百分位反算，
  可抵消不同年份考生规模变化。仅当两年都拿到 cohort_size 时可用，否则自动回退 rank 法
  并在 ``caveat`` 里说明。

诚实口径：锚点是稀疏的（每省每科类 3~5 个批次/层次线），区间内线性插值、区间外按端点
斜率外推并标注 ``extrapolated``。结果仅供学习参考，正式填报以各省考试院一分一段表为准。
"""
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_SCORE_TABLES = os.path.join(_DATA_DIR, "score_tables.json")
_OFFICIAL = os.path.join(_DATA_DIR, "admission_official_2024.json")
_REAL = os.path.join(_DATA_DIR, "admission_real_baseline.json")
_SAMPLE = os.path.join(_DATA_DIR, "admission_sample.json")

# 与 admission.SUBJECT_ALIASES 保持一致：内容侧用「综合/未改革」，数据侧用「综合」
SUBJECT_ALIASES = {"综合/未改革": "综合", "综合类": "综合"}

SCORE_MIN, SCORE_MAX = 0, 750
RANK_MAX = 2_000_000

_CACHE = {}

_SOURCE_LABEL = {
    "official": "官方省控线/投档线",
    "official_table": "官方一分一段表",
    "estimated": "模型估算基线",
    "sample": "参数化样例",
}


def _norm_subject(subject: str) -> str:
    return SUBJECT_ALIASES.get(subject, subject)


def _load_json(path: str) -> dict:
    if path in _CACHE:
        return _CACHE[path]
    data = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    _CACHE[path] = data
    return data


def invalidate_cache() -> None:
    """同步/更新数据后调用：清空进程内缓存。"""
    _CACHE.clear()


# ------------------------------------------------------------ 锚点构建

def _anchor(tier, score, rank, source, line=None):
    return {"tier": tier, "score": score, "rank": rank, "data_source": source, "line": line}


def _anchors_from_official(province: str, subject: str) -> list:
    off = _load_json(_OFFICIAL)
    if not off:
        return []
    batch = off.get("batch_lines", {}).get(province, {}).get(subject, {})
    school = off.get("school_tier_lines", {}).get(province, {}).get(subject, {})
    out = []
    for tier, v in batch.items():
        out.append(_anchor(tier, v["score"], v["rank"], "official", v.get("line")))
    for tier, v in school.items():
        out.append(_anchor(tier, v["score"], v["rank"], "official", v.get("school")))
    return out


def _anchors_from_baseline(path: str, province: str, subject: str, source: str) -> list:
    data = _load_json(path)
    if not data:
        return []
    tiers = data.get("tier_baseline", {}).get(province, {}).get(subject)
    if not tiers:
        return []
    out = []
    for tier, v in tiers.items():
        out.append(_anchor(tier, v["min_score"], v["min_rank"], source))
    return out


def _anchors_from_score_tables(province: str, subject: str, year: int):
    """真实一分一段表（可选覆盖层）：返回 (anchors, cohort_size)。"""
    tables = _load_json(_SCORE_TABLES)
    if not tables:
        return [], None
    node = tables.get(province, {}).get(subject, {}).get(str(year))
    if not node:
        return [], None
    points = node.get("points") or []
    anchors = [_anchor(f"{p[0]}分", p[0], p[1], "official_table") for p in points if len(p) >= 2]
    return anchors, node.get("cohort_size")


def _year_of(path: str, default: int) -> int:
    data = _load_json(path)
    try:
        return int(data.get("meta", {}).get("year", default))
    except (TypeError, ValueError):
        return default


def _clean(anchors: list) -> list:
    """排序（位次升序）+ 去掉无效/重复位次项。同一位次保留分数更高者。"""
    valid = [a for a in anchors
             if isinstance(a.get("score"), (int, float)) and isinstance(a.get("rank"), (int, float))
             and a["rank"] > 0]
    valid.sort(key=lambda a: (a["rank"], -a["score"]))
    out = []
    for a in valid:
        if out and out[-1]["rank"] == a["rank"]:
            continue
        out.append(a)
    return out


def curve(province: str, subject: str, year: int) -> dict:
    """返回某省/科类/年份的「位次→分数」锚点曲线。

    结构：``{"ok":True, "year":…, "province":…, "subject":…, "data_source":…,
    "cohort_size":…|None, "anchors":[{"tier","score","rank","data_source","line"}]}``
    锚点按位次升序（位次越小＝分数越高）。
    """
    subject_n = _norm_subject(subject)
    anchors, cohort = _anchors_from_score_tables(province, subject_n, year)
    source = "official_table"

    if not anchors and year == _year_of(_OFFICIAL, 2024):
        anchors = _anchors_from_official(province, subject_n)
        source = "official"
    if not anchors:
        if year == _year_of(_REAL, 0):
            anchors = _anchors_from_baseline(_REAL, province, subject_n, "estimated")
            source = "estimated"
        elif year == _year_of(_SAMPLE, 0):
            anchors = _anchors_from_baseline(_SAMPLE, province, subject_n, "sample")
            source = "sample"

    anchors = _clean(anchors)
    if len(anchors) < 2:
        return {"ok": False, "error": f"暂无 {province}/{subject} {year} 年的分数—位次锚点"}
    return {"ok": True, "year": year, "province": province, "subject": subject,
            "data_source": source, "cohort_size": cohort, "anchors": anchors}


def available_years(province: str, subject: str) -> list:
    """该省/科类可用年份列表（含数据源标签与锚点数），按年份降序。

    只列「真实可用」的年份：``sample``（参数化样例，年份是虚构的演示值）不参与换算，
    否则用户会把 2025 样例年当成真实年份去换算，得到看似精确的错误结论。
    """
    years = {}
    for path in (_OFFICIAL, _REAL):
        y = _year_of(path, 0)
        if not y:
            continue
        c = curve(province, subject, y)
        if c.get("ok") and c.get("data_source") != "sample":
            years[y] = {"year": y, "data_source": c["data_source"], "anchors": len(c["anchors"])}
    tables = _load_json(_SCORE_TABLES)
    for y in tables.get(province, {}).get(_norm_subject(subject), {}):
        try:
            yi = int(y)
        except ValueError:
            continue
        c = curve(province, subject, yi)
        if c.get("ok"):
            years[yi] = {"year": yi, "data_source": c["data_source"], "anchors": len(c["anchors"])}
    return sorted(years.values(), key=lambda x: -x["year"])


# ------------------------------------------------------------ 插值

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def score_of_rank(cur: dict, rank: float) -> tuple:
    """位次 → 分数（分段线性插值；区间外按端点斜率外推）。返回 (score, extrapolated)。

    恰落在某个锚点上时不算外推（早期版本用 ``<=``，把「正好是省控线位次」也标成外推，
    前端会误报「落在锚点区间之外」）。
    """
    pts = cur["anchors"]
    if rank < pts[0]["rank"]:
        x1, y1 = pts[0]["rank"], pts[0]["score"]
        x2, y2 = pts[1]["rank"], pts[1]["score"]
        slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
        return _clamp(round(y1 + slope * (rank - x1), 1), SCORE_MIN, SCORE_MAX), True
    if rank > pts[-1]["rank"]:
        x1, y1 = pts[-2]["rank"], pts[-2]["score"]
        x2, y2 = pts[-1]["rank"], pts[-1]["score"]
        slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
        return _clamp(round(y2 + slope * (rank - x2), 1), SCORE_MIN, SCORE_MAX), True
    for i in range(1, len(pts)):
        if rank <= pts[i]["rank"]:
            x1, y1 = pts[i - 1]["rank"], pts[i - 1]["score"]
            x2, y2 = pts[i]["rank"], pts[i]["score"]
            t = (rank - x1) / (x2 - x1) if x2 != x1 else 0
            return round(y1 + t * (y2 - y1), 1), False
    return pts[-1]["score"], False


def rank_of_score(cur: dict, score: float) -> tuple:
    """分数 → 位次（反向插值；分数越高位次越小）。返回 (rank, extrapolated)。"""
    pts = cur["anchors"]
    if score > pts[0]["score"]:
        x1, y1 = pts[0]["score"], pts[0]["rank"]
        x2, y2 = pts[1]["score"], pts[1]["rank"]
        slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
        return int(_clamp(round(y1 + slope * (score - x1)), 1, RANK_MAX)), True
    if score < pts[-1]["score"]:
        x1, y1 = pts[-2]["score"], pts[-2]["rank"]
        x2, y2 = pts[-1]["score"], pts[-1]["rank"]
        slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
        return int(_clamp(round(y2 + slope * (score - x2)), 1, RANK_MAX)), True
    for i in range(1, len(pts)):
        if score >= pts[i]["score"]:
            x1, y1 = pts[i - 1]["score"], pts[i - 1]["rank"]
            x2, y2 = pts[i]["score"], pts[i]["rank"]
            t = (score - x1) / (x2 - x1) if x2 != x1 else 0
            return int(_clamp(round(y1 + t * (y2 - y1)), 1, RANK_MAX)), False
    return pts[-1]["rank"], False


# ------------------------------------------------------------ 换算入口

def convert(province: str, subject: str, year: int, target_year: int,
            score: float = None, rank: int = None, method: str = "rank") -> dict:
    """等位分换算主入口。

    入参：``score`` 与 ``rank`` 至少给一个（同时给出时以 rank 为准）。
    出参：源年分数/位次、目标年等效分数/位次、锚点与方法说明。
    """
    if score is None and rank is None:
        return {"ok": False, "error": "请提供 score 或 rank"}
    if year == target_year:
        return {"ok": False, "error": "源年份与目标年份相同，无需换算"}

    src = curve(province, subject, year)
    if not src["ok"]:
        return src
    dst = curve(province, subject, target_year)
    if not dst["ok"]:
        return dst

    caveats = []
    # 0) 口径提示：官方省控线锚点与估算基线锚点混用会放大误差，必须显式说明
    if src.get("data_source") != dst.get("data_source"):
        caveats.append(
            f"源年锚点为「{_SOURCE_LABEL.get(src.get('data_source'), src.get('data_source'))}」、"
            f"目标年为「{_SOURCE_LABEL.get(dst.get('data_source'), dst.get('data_source'))}」，"
            "两年口径不同，换算偏差可能较大")
    # 1) 源年：拿到 (score, rank)
    if rank is not None:
        if not (isinstance(rank, int) and not isinstance(rank, bool)) or rank <= 0:
            return {"ok": False, "error": "位次必须为正整数"}
        if rank > RANK_MAX:
            return {"ok": False, "error": f"位次超出合理范围（上限 {RANK_MAX}）"}
        s_rank = rank
        s_score, s_ext = score_of_rank(src, s_rank)
    else:
        if not (SCORE_MIN <= score <= SCORE_MAX):
            return {"ok": False, "error": f"分数需在 {SCORE_MIN}~{SCORE_MAX} 之间"}
        s_score = float(score)
        s_rank, s_ext = rank_of_score(src, s_score)
    if s_ext:
        caveats.append("源年分数/位次落在锚点区间之外，为端点斜率外推值")

    # 2) 目标年：按方法换算
    method_used = method if method in ("rank", "percentile") else "rank"
    cohort_src, cohort_dst = src.get("cohort_size"), dst.get("cohort_size")
    if method_used == "percentile":
        if not cohort_src or not cohort_dst:
            method_used = "rank"
            caveats.append("缺少考生规模（cohort_size），percentile 法不可用，已回退为 rank 法")
        else:
            pct = min(1.0, s_rank / cohort_src)
            t_rank = int(_clamp(round(pct * cohort_dst), 1, RANK_MAX))
            t_score, t_ext = score_of_rank(dst, t_rank)
            if t_ext:
                caveats.append("目标年换算落在锚点区间之外，为端点斜率外推值")
            return _pack(province, subject, src, dst, s_score, s_rank, t_score, t_rank,
                         method_used, pct, caveats, t_ext)

    t_score, t_ext = score_of_rank(dst, s_rank)
    t_rank = s_rank
    if t_ext:
        caveats.append("目标年换算落在锚点区间之外，为端点斜率外推值")
    pct = (s_rank / cohort_src) if cohort_src else None
    return _pack(province, subject, src, dst, s_score, s_rank, t_score, t_rank,
                 method_used, pct, caveats, t_ext)


def _pack(province, subject, src, dst, s_score, s_rank, t_score, t_rank,
          method, pct, caveats, t_ext) -> dict:
    return {
        "ok": True,
        "province": province, "subject": subject,
        "from": {"year": src["year"], "score": s_score, "rank": s_rank,
                 "data_source": src["data_source"], "anchors": src["anchors"]},
        "to": {"year": dst["year"], "score": t_score, "rank": t_rank,
               "data_source": dst["data_source"], "anchors": dst["anchors"]},
        "delta_score": round(t_score - s_score, 1),
        "percentile": round(pct, 4) if pct is not None else None,
        "method": method,
        "extrapolated": bool(t_ext),
        "caveat": "；".join(caveats),
        "note": "锚点为稀疏批次/层次线，区间内线性插值、区间外斜率外推；仅供学习参考，"
                "正式填报以各省考试院一分一段表为准。",
    }
