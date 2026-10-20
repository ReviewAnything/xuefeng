"""院校推荐（A3）：按用户位次给出 冲/稳/保 三档院校清单。

思路
----
1. 先用既有录取基线（``admission.major_thresholds``，含 11 省官方省控线覆盖层）
   算出各层次（985 / 211 / 普通一本 / 普通二本 / 专科）的门槛位次；若指定专业，
   再叠加该专业的难度系数。
2. 再用 ``admission.classify`` 把用户位次与门槛位次比较，得到 冲/稳/保/不可及。
3. 最后从教育部全国高校名单（2868 所）里，按层次圈定院校池并排序输出。

诚实口径（务必展示给用户）
--------------------------
- 985/211 档的院校是「真实名单」，但档内不区分具体录取线；
- 普通一本/二本/专科没有逐校投档位次数据，给出的是**同层次院校池**
  （可按省份/办学性质/门类进一步过滤），必须对照往年投档线人工筛选。
因此每条推荐都带 ``basis`` 说明，前端需原样展示，避免把「院校池」误读成「能上」。
"""
from . import admission as A
from . import school_lines as SL

# 层次 → 院校池筛选条件（tier 走 985/211 标记，其余走办学层次）
TIER_POOL = {
    "985": {"kind": "tier", "value": "985", "label": "985 高校"},
    "211": {"kind": "tier", "value": "211", "label": "211 高校（不含 985）"},
    "普通一本": {"kind": "level", "value": "本科", "label": "普通本科院校"},
    "普通二本": {"kind": "level", "value": "本科", "label": "普通本科院校"},
    "专科": {"kind": "level", "value": "专科", "label": "高职专科院校"},
}

LEVEL_ORDER = {"冲": 0, "稳": 1, "保": 2, "不可及": 3}

MAX_LIMIT = 50


def _major_of(name: str):
    if not name:
        return None
    from .content import MAJORS
    return next((m for m in MAJORS if m["name"] == name), None)


def _pick_pool(tier: str, province: str = None, nature: str = None,
               category: str = None, q: str = None) -> list:
    """取某层次的院校池（教育部名单）。211 档剔除 985，避免与 985 档重复。"""
    cfg = TIER_POOL.get(tier)
    if not cfg:
        return []
    kwargs = {"limit": 3000}
    if cfg["kind"] == "tier":
        kwargs["tier"] = cfg["value"]
    else:
        kwargs["level"] = cfg["value"]
    if nature:
        kwargs["nature"] = nature
    if category:
        kwargs["category"] = category
    if q:
        kwargs["q"] = q

    res = A.universities(**kwargs)
    if not res.get("ok"):
        return []
    items = res["universities"]

    if cfg["kind"] == "level":
        # 普通本科池剔除 985/211（那些已在上两档单独列出）
        items = [u for u in items if not u.get("is_211")]
    elif cfg["value"] == "211":
        items = [u for u in items if not u.get("is_985")]
    return items


def _sort_key(u, home_province: str):
    """排序：本省优先 → 公办优先 → 985/211 优先 → 名称。"""
    local = 0 if (home_province and u.get("province") == home_province) else 1
    pub = 0 if u.get("nature") == "公办" else 1
    elite = 0 if (u.get("is_985") or u.get("is_211") or u.get("is_dfc")) else 1
    return (local, pub, elite, u.get("name") or "")


def recommend_schools(province: str, subject: str, user_rank: int,
                      major_name: str = None, limit: int = 12,
                      nature: str = None, category: str = None,
                      q: str = None, prefer_local: bool = True) -> dict:
    """按位次推荐 冲/稳/保 院校。

    - ``major_name``：可选。给出后按该专业的难度系数调整各层次门槛。
    - ``prefer_local``：本省院校优先（本省招生计划通常更多，命中率更高）。
    """
    err = A.validate_user_rank(user_rank)
    if err:
        return {"ok": False, "error": err}

    major = _major_of(major_name)
    if major_name and not major:
        return {"ok": False, "error": f"未找到专业：{major_name}"}
    major_cat = major["cat"] if major else None

    th = A.major_thresholds(province, subject, major_name or "", major_cat or "")
    if not th["ok"]:
        return th

    limit = max(1, min(int(limit or 12), MAX_LIMIT))
    tiers = []
    for t in th["tiers"]:
        tier = t["tier"]
        level = A.classify(user_rank, t["min_rank"])
        pool = _pick_pool(tier, province=province, nature=nature, category=category, q=q)
        pool.sort(key=lambda u: _sort_key(u, province if prefer_local else None))
        schools = [{
            "name": u["name"], "province": u.get("province"), "city": u.get("city"),
            "level": u.get("level"), "nature": u.get("nature"), "category": u.get("category"),
            "is_985": u.get("is_985", False), "is_211": u.get("is_211", False),
            "is_dfc": u.get("is_dfc", False), "website": u.get("website"),
        } for u in pool[:limit]]
        tiers.append({
            "tier": tier,
            "level": level,
            "min_score": t["min_score"],
            "min_rank": t["min_rank"],
            "data_source": t.get("data_source", "estimated"),
            "line": t.get("line"),
            "pool_label": TIER_POOL.get(tier, {}).get("label", tier),
            "pool_total": len(pool),
            "schools": schools,
            "basis": _basis(tier),
        })

    tiers.sort(key=lambda x: (LEVEL_ORDER.get(x["level"], 9), x["min_rank"]))

    # D1：如果该省已导入院校级投档线，给每条院校挂上真实最低分/位次；
    # 未导入则保持空值，前端继续按层次提示，不假装精确。
    all_names = [s["name"] for t in tiers for s in t["schools"]]
    lines = SL.map_for(province, subject, all_names)
    for t in tiers:
        hits = 0
        for s in t["schools"]:
            rec = lines.get(s["name"])
            if not rec:
                s["min_score"] = None
                s["min_rank"] = None
                s["line_year"] = None
                s["data_source"] = "estimated"
                continue
            s["min_score"] = rec["min_score"]
            s["min_rank"] = rec["min_rank"]
            s["line_year"] = rec["year"]
            s["group_code"] = rec.get("group_code") or ""
            s["data_source"] = "school_line"
            hits += 1
        t["school_line_hits"] = hits
        t["basis"] = _basis(t["tier"], hits)

    summary = {"reach": 0, "match": 0, "safe": 0, "unreachable": 0}
    key = {"冲": "reach", "稳": "match", "保": "safe", "不可及": "unreachable"}
    for t in tiers:
        summary[key[t["level"]]] += 1

    total_hits = sum(t.get("school_line_hits", 0) for t in tiers)
    notes = [
        "985/211 档为教育部官方名单，档内未区分具体录取线；"
        "普通本科/专科档为同层次院校池，非「按你的位次录得到」的名单。",
        "最终筛选请对照本省考试院/院校招生网公布的往年投档位次。",
    ]
    if total_hits:
        notes.insert(0, f"本次展开的 {len(all_names)} 所院校中，{total_hits} 所已匹配到院校级投档线"
                        "（行内标注「去年最低」），其余仍为层次估算。")
    else:
        notes.insert(0, "该省尚未导入院校级投档线，院校行不含「去年最低分」；"
                        "可在管理端「校线导入」上传本省投档表后重新生成。")

    return {
        "ok": True, "province": province, "subject": subject, "user_rank": user_rank,
        "major": major["name"] if major else None,
        "data_source": th.get("data_source", "estimated"),
        "official_provinces": A.official_coverage(),
        "tiers": tiers, "summary": summary, "limit": limit,
        "school_line_hits": total_hits,
        "notes": notes,
    }


def _basis(tier: str, school_line_hits: int = 0) -> str:
    """每档的诚实口径；有校线数据时明确说明「部分院校为真实投档线」。"""
    if tier == "985":
        base = "985 高校官方名单；门槛为该省 985 入门投档位次"
    elif tier == "211":
        base = "211 高校官方名单（不含 985）；门槛为该省 211 入门投档位次"
    elif tier == "专科":
        base = "教育部高职专科院校池；门槛为该省专科批控制线位次"
    else:
        base = "教育部普通本科院校池；门槛为该省本科批次控制线位次"
    if school_line_hits:
        return base + f"；其中 {school_line_hits} 所有已导入的院校投档线（标注「去年最低」）"
    return base
