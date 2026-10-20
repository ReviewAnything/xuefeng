"""结论：把位次翻译成一句判断 + 三个动作。

设计约束
--------
1. 只说数据支撑得起的话。985 / 211 / 本科 / 专科 四道门来自省控线与官方入门投档位次；
   具体某一所学校能不能上，需要校级投档线，缺数据时宁可只给区间，也不编校名。
2. 输出是「主张」，不是「看板」：一句结论 + 三个动作 + 一条保底红线。
   口径、来源、沿用年份全部收进 `basis` 一行，不占结论位置。
3. 用断言，不用商量。"可能""大概""仅供参考""请以…为准" 一旦出现在结论页，
   等于把判断推回给用户 —— 那就不叫结论页。
"""

from . import admission as A

# 冲/稳/保：以「院校去年投档位次 / 你的位次」的倍数定义。
#   0.70–0.92×：学校线在你之前 → 冲
#   0.92–1.12×：差不多 → 稳
#   1.12–1.50×：学校线在你之后 → 保
BAND_RULES = (
    ("reach", "冲", 0.70, 0.92),
    ("match", "稳", 0.92, 1.12),
    ("safe", "保", 1.12, 1.50),
)

TIER_LABEL = {"985": "985", "211": "211", "普通一本": "一本",
              "普通二本": "本科", "专科": "专科"}

# 211 门槛余量：门槛位次 / 你的位次。低于该值说明只剩尾部院校可进。
AMPLE_MARGIN = 2.0

_ROSTER = None


def _roster() -> list:
    global _ROSTER
    if _ROSTER is None:
        _ROSTER = A._load_national().get("universities", [])
    return _ROSTER


def _local_211(province: str) -> tuple:
    """省内 211 名单 → (全部, 非 985)。仅用于说明院校结构，不做录取可行性判断。"""
    all211 = [u["name"] for u in _roster()
              if u.get("province") == province and u.get("is_211")]
    real = [u["name"] for u in _roster()
            if u.get("province") == province and u.get("is_211") and not u.get("is_985")]
    return all211, real


def _round100(n: float) -> int:
    return max(1, int(round(n / 100.0)) * 100)


def _names(names: list, limit: int = 3) -> str:
    """结论页只点名三所，剩下的给数量 —— 一屏塞 18 个校名，等于没给建议。"""
    if len(names) <= limit:
        return "、".join(names)
    return "、".join(names[:limit]) + f" 等 {len(names)} 所"


def _bands(user_rank: int) -> list:
    return [{
        "key": key, "label": label,
        "from": _round100(user_rank * lo), "to": _round100(user_rank * hi),
    } for key, label, lo, hi in BAND_RULES]


def _gates(tiers: list, user_rank: int) -> list:
    out = []
    for t in tiers:
        min_rank = int(t["min_rank"])
        gap = min_rank - user_rank          # ≥0 位次在门内（数值越大越松）
        out.append({
            "tier": t["tier"],
            "label": TIER_LABEL.get(t["tier"], t["tier"]),
            "min_rank": min_rank,
            "min_score": t["min_score"],
            "school": t.get("school") or None,
            "state": "open" if gap >= 0 else "closed",
            "gap": gap,
            "data_source": t.get("data_source", "estimated"),
            "source_year": t.get("source_year"),
            "carried": bool(t.get("carried")),
        })
    return out


def _case(gates: list, r: int) -> str:
    g = {x["tier"]: x for x in gates}
    for tier, name in (("985", "has_985"), ("211", "has_211"),
                       ("普通二本", "has_ben"), ("专科", "has_zhuan")):
        if g.get(tier) and r <= g[tier]["min_rank"]:
            return name
    return "below_all"


def _school_txt(gate: dict) -> str:
    """有校名就点名，没有就只说门槛（推算基线没有校名，不能硬编）。"""
    return f"（{gate['school']}）" if gate.get("school") else ""


def build(province: str, subject: str, user_rank: int) -> dict:
    """返回结论页数据。失败时 ok=False + error，由路由层转 HTTP 错误。"""
    err = A.validate_user_rank(user_rank)
    if err:
        return {"ok": False, "error": err}

    th = A.major_thresholds(province, subject, "", "")
    if not th.get("ok"):
        return {"ok": False, "error": th.get("error") or "暂无该省数据"}

    subject = th["subject"]
    r = user_rank
    gates = _gates(th["tiers"], r)
    g = {x["tier"]: x for x in gates}
    g985, g211 = g.get("985"), g.get("211")
    g_ben, g_zhuan = g.get("普通二本"), g.get("专科")
    bands = _bands(r)
    local_all, local_real = _local_211(province)
    nat_211 = sum(1 for u in _roster() if u.get("is_211"))
    case = _case(gates, r)

    # 本科线内的百分位：只在本科线之前有意义（掉到线后算出来会 >100%）
    pct = (r / g_ben["min_rank"] * 100) if (g_ben and r <= g_ben["min_rank"]) else None

    stance, facts = [], []
    guard = f"保底最远填到 {bands[2]['to']} 名：再往后的学校，你的分是白扔的。"

    # ------------------------------------------------ 判定
    if case == "has_985":
        headline = (f"{r} 名，985 的门没挡住你。全省最低的一所"
                    f"{_school_txt(g985)}去年落到 {g985['min_rank']} 名，你比它高 {g985['gap']} 位。")
        stance = [
            {"k": "别犹豫", "t": f"第一志愿直接给 985。你不是在「冲」，你是进得去。"},
            {"k": "铺开填", "t": "985 在你这一档不止一所，按城市和专业组排一遍，"
                              "别在志愿表上只写一个名字。"},
            {"k": "留后手", "t": f"保底放到 {bands[2]['to']} 名，两所，选你确定愿意读的。"},
        ]

    elif case == "has_211":
        margin = g211["min_rank"] / r
        if margin >= AMPLE_MARGIN:
            headline = (f"{r} 名。985 关门——全省最低的一所"
                        f"{_school_txt(g985)}去年卡在 {g985['min_rank']} 名，"
                        f"你差 {r - g985['min_rank']} 位，一个志愿都别浪费在上面。")
            if local_real:
                stance.append({
                    "k": "主攻",
                    "t": f"你的战场是 211。{province}全省 {len(local_all)} 所 211，"
                         f"扣掉 985 只剩 {len(local_real)} 所（{_names(local_real)}）——"
                         f"一个省填不满你的志愿表，必须往外省放。",
                })
            else:
                stance.append({
                    "k": "主攻",
                    "t": f"你的战场是 211。{province}省内没有非 985 的 211，"
                         f"志愿表只能靠外省那 {nat_211 - len(local_all)} 所 211 来填。",
                })
            stance.append({
                "k": "换位次",
                "t": "同样牌子的学校，在生源弱的省投档位次更低 —— 拿你的位次出省，"
                     "买到的是同一个校名，不是同一个概率。",
            })
            stance.append({
                "k": "保底",
                "t": f"保底卡在 {bands[2]['from']}–{bands[2]['to']} 名。再往下，你的分就白扔了。",
            })
        else:
            headline = (f"{r} 名。985 关门，211 只剩一条缝——211 里最低的一所"
                        f"{_school_txt(g211)}去年 {g211['min_rank']} 名，你只比它高 "
                        f"{g211['min_rank'] - r} 位。")
            stance = [
                {"k": "别当主攻", "t": "211 里你能进的只有尾部那几所。放两个志愿当彩票，"
                                  "主攻不要放在这里。"},
                {"k": "挑专业", "t": "这个位次买不到牌子，但买得到专业。同样分数的两所学校，"
                                "先看专业组里有没有你绝对不读的专业：有，就换一所。"},
                {"k": "保底", "t": f"保底卡在 {bands[2]['from']}–{bands[2]['to']} 名，"
                                f"留两所你确定愿意去的。"},
            ]

    elif case == "has_ben":
        ref = g211 or g985
        pos = "前段" if (pct or 100) <= 30 else ("中段" if (pct or 100) <= 70 else "后段")
        headline = (f"{r} 名。985、211 都关门"
                    + (f"（211 最低的一所卡在 {ref['min_rank']} 名）" if ref else "")
                    + f"，你落在本科批的{pos}。")
        stance = [
            {"k": "换目标", "t": "这个位次决定不了学校牌子，只决定专业。"
                              "别在「像不像名校」上耗时间，去比专业组的就业出口。"},
            {"k": "挑组不挑校", "t": "同样分数的两所学校，先看专业组里有没有你绝对不读的专业："
                                "有，就换一所。被调剂进不读的专业，四年都是成本。"},
            {"k": "保底", "t": f"保底卡在 {bands[2]['from']}–{bands[2]['to']} 名，"
                            f"往下留两所你确定愿意去的。"},
        ]

    elif case == "has_zhuan":
        headline = (f"{r} 名，本科线（{g_ben['min_rank']} 名）在你前面 {r - g_ben['min_rank']} 位。"
                    f"这个位次不选学校，选一条能往上走的路。")
        stance = [
            {"k": "先选路", "t": "专科批里，公办高职的王牌专业强于民办本科的冷门专业。"
                             "前者直接就业，后者只是把同一个问题推迟四年。"},
            {"k": "留后门", "t": "优先选有专升本通道、且升本率公开的学校 —— 这是三年后唯一的翻盘点。"},
            {"k": "别复读", "t": "除非你确定这次是失常而不是实力，否则复读一年换来的位次，"
                             "买不回这一年。"},
        ]

    else:  # 连专科线都没到
        headline = (f"{r} 名，专科线（{g_zhuan['min_rank']} 名）也在你前面。"
                    f"这时候谈志愿表没有意义，谈路径。")
        stance = [
            {"k": "别将就", "t": "别把志愿表填成「有学上就行」—— 专科里也有毕业即失业的专业。"},
            {"k": "选赛道", "t": "只看有对口单位的专业：护理、轨交、电力、数控这一类，"
                             "进去就知道毕业去哪。"},
            {"k": "复读", "t": "这次是失常，复读是唯一能重置位次的动作；是实力，就别浪费这一年。"},
        ]
        guard = "这一档没有保底可言：先决定路径，再谈学校。"

    # ------------------------------------------------ 事实（有数字才叫事实）
    if pct is not None:
        facts.append(f"在 {province}{subject}本科线内的考生里，你排前 {pct:.1f}%。")

    if case in ("has_985", "has_211"):
        if local_all:
            tail = f"；其中 {len(local_real)} 所不是 985。" if len(local_real) != len(local_all) else "。"
            facts.append(f"{province}全省 211 共 {len(local_all)} 所："
                         + "、".join(local_all) + tail)
        else:
            facts.append(f"{province}省内没有 211；全国 {nat_211} 所 211 全在外省。")
        if g985:
            facts.append(f"985 的入门线{_school_txt(g985)}：{g985['min_rank']} 名 / {g985['min_score']} 分。")
        if g211:
            facts.append(f"211 的入门线{_school_txt(g211)}：{g211['min_rank']} 名 / {g211['min_score']} 分。")

    if case == "has_ben" and g_ben:
        facts.append(f"本科批门槛：{g_ben['min_rank']} 名 / {g_ben['min_score']} 分，"
                     f"你在它前面 {g_ben['min_rank'] - r} 位。")
    if case in ("has_zhuan", "below_all") and g_zhuan:
        facts.append(f"专科批门槛：{g_zhuan['min_rank']} 名 / {g_zhuan['min_score']} 分。")

    # ------------------------------------------------ 口径（一行，不铺开）
    years = sorted({x["source_year"] for x in gates if x.get("source_year")})
    official = any(x["data_source"] == "official" for x in gates)
    carried = any(x["carried"] for x in gates)
    if official and years:
        basis = f"依据 {years[-1]} 年{province}省控线与 985/211 入门投档位次"
        if carried:
            basis += "（当年未更新，沿用值）"
    elif official:
        basis = f"依据{province}省控线"
    else:
        basis = f"依据推算基线（{province}无官方省控线数据）"

    return {
        "ok": True,
        "case": case,
        "province": province,
        "subject": subject,
        "user_rank": r,
        "headline": headline,
        "stance": stance,
        "guard": guard,
        # 连专科线都没到的时候，冲稳保区间没有意义，不给
        "bands": bands if case != "below_all" else [],
        "gates": gates,
        "facts": facts,
        "basis": basis,
        "data_source": th.get("data_source"),
    }
