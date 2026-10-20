"""P2 核心：观点 × 数据 交叉核验。

语义分层（设计评审 S0 / S2 落地）
------------------------
  - ``reachability``（可及性）：候选位次能否触及该专业观点所隐含的质量层次。
    这是对「考生自己」的事实陈述，由「观点 × 可达批次门槛」决定，诚实且无歧义。
  - ``alignment``（证据一致性）：数据是否真正支持/反驳观点。
    S2 起，导入真实逐校投档线（``school_lines``，掌上高考 2025 真实录取记录）
    后，``alignment`` 变为可计算的「可及性核验」：
      - ``supported``：真实数据显示候选位次可触及开设该专业领域的院校层次；
      - ``refuted``：真实数据显示候选位次够不到任何开设该专业领域的院校；
      - ``unverified``：该 (省/科类) 暂无真实校线数据，**或校线样本量不足以支撑判断**
        （S7-C 证据门槛；单侧降级，不出现"一致/冲突"）。
    设计红线：数据侧（校线）只能核验「能否读到」，**不能**核验专业就业价值本身；
    所有 alignment 文案都显式声明这一点，绝不把"够不够"伪装成"值不值"。

S7-C 增补「证据门槛 + 单侧降级」：一条校线就敢说「支持/反驳」是把**对置版式**
（观点 vs 数据）变成了无信息放大——样本太薄时那句判断其实什么都没证明。现在
``alignment`` 只有在样本量过门槛时才给强判断，否则一律降级为 ``unverified`` 并
在 ``alignment_basis`` 里写清「为什么不敢判」（校线条数/覆盖院校数/数据等级）。
**只降级、不升级**：证据不足永远往 unverified 退，绝不反向推出"观点成立"。
  - ``sources``：对置版式的双来源——观点来源（content.json）+ 数据来源（真实校线），
    每条都带可点击的原始数据链接（``source_url``），满足"逐条展示两种来源、原始数据点击可达"。
"""
from .admission import analyze_major, validate_user_rank
from .content import VIEW_LABEL
from . import school_lines as SL
from sqlalchemy import select
from db.database import session_scope
from db.models import SchoolLine
from db import repository as _repo

# 高危低位次批次：在这些批次读到「推荐」专业，原 bias 提示的风险会被放大
LOW_TIERS = {"普通二本", "专科"}

# 可及性分级：最受限 → 最宽裕（批量排序用，风险优先）
REACHABILITY_ORDER = {"out_of_reach": 0, "low": 1, "mid": 2, "high": 3}
REACHABILITY_LABEL = {
    "out_of_reach": "位次不可及",
    "low": "仅够低层次",
    "mid": "可达一本",
    "high": "可达高层次",
}

# 证据一致性（S2 起可计算；缺真实校线时恒为 unverified）
ALIGNMENT_UNVERIFIED = "unverified"
ALIGNMENT_LABEL = {
    "unverified": "数据未覆盖",
    "supported": "数据可及",
    "refuted": "数据不可及",
}


def _reachability(view: str, best_tier) -> str:
    """候选位次相对观点隐含层次的真实可及性。"""
    if best_tier is None:
        return "out_of_reach"
    if best_tier in LOW_TIERS:
        return "low"
    if best_tier == "普通一本":
        return "mid"
    return "high"  # 985 / 211


def _reachability_message(major_name: str, view: str, best: dict, reach: str) -> str:
    """可及性提示：只描述「你的位次能摸到哪个层次」，不宣称数据支持/反驳观点。"""
    if reach == "out_of_reach":
        floor = best["min_rank"] if best else "—"
        return (f"你的位次在所有批次都够不到「{major_name}」"
                f"（最易批次门槛位次 {floor}），"
                f"建议优先看冲稳保梯度内的专业。")
    tier = best["tier"]
    level = best["level"]
    rank = best["min_rank"]
    if view == "recommend":
        if reach == "low":
            return (f"「{major_name}」观点为<b>推荐</b>，但你的位次只能摸到"
                    f"<b>{tier}</b>层次（门槛位次 {rank}，判定「{level}」）。"
                    f"推荐通常假设进入较优质培养单位，低位次段就读时原 bias 提示的风险会被放大。"
                    f"这是<b>可及性</b>提示，不代表数据否定该观点。")
        return (f"「{major_name}」观点为<b>推荐</b>，且你的位次可够到"
                f"<b>{tier}</b>层次（门槛位次 {rank}，判定「{level}」）——"
                f"推荐所隐含的「较优质培养单位」前提成立。这是<b>可及性</b>提示，"
                f"数据侧暂无法核验观点本身。")
    if view == "caution":
        return (f"「{major_name}」观点为<b>慎选</b>，你的位次可摸到"
                f"<b>{tier}</b>层次（判定「{level}」）。"
                f"该专业并非完全不可，但需满足条件（如深造/转方向）才成立。"
                f"这是<b>可及性</b>提示，数据侧暂无法核验观点本身。")
    # avoid
    if reach == "low":
        return (f"「{major_name}」观点为<b>避坑</b>，而你的位次正好落在"
                f"<b>{tier}</b>层次——这恰是该观点最不推荐的处境，"
                f"需重点评估 bias 例外方向。这是<b>可及性</b>提示，数据侧暂无法核验观点本身。")
    return (f"「{major_name}」观点为<b>避坑</b>，但你的位次能摸到"
            f"<b>{tier}</b>层次（判定「{level}」）。"
            f"若你确有资源/热爱，可在充分了解风险后谨慎考虑。"
            f"这是<b>可及性</b>提示，数据侧暂无法核验观点本身。")


def _suggestions(view: str, bias: str, reach: str) -> list:
    if reach == "out_of_reach":
        return [
            "回到诊断画布查看可达专业清单（数据侧已按你的位次筛出 冲/稳/保）",
            "若坚持该专业，需显著提高位次或考虑同大类更易录取的方向",
        ]
    base = [f"仍需核对 bias 提示，避免把观点当定论：{bias}"]
    if view == "recommend":
        if reach == "low":
            return base + [
                "若只能读低位次院校，优先选同大类中门槛更低但仍有壁垒的方向",
                "用资源中心的 gaokao-advisor 核验该专业在你位次段的真实招生量",
            ]
        return base + ["用资源中心工具核验该专业目标院校的真实录取位次波动"]
    if view == "caution":
        return [
            f"关键看 bias 提示里的「前提条件」：{bias}",
            "仅在能满足前提（如坚定读研、能啃硬课）时纳入",
        ]
    # avoid
    if reach == "low":
        return [
            f"务必阅读 bias 提示里的「例外方向」：{bias}",
            "优先用数据侧筛出的 稳/保 专业替换",
        ]
    return [
        f"仅当满足 bias 提示中的例外（如热爱科研且规划读博）才考虑：{bias}",
        "普通家庭无背景时，建议仍按避坑处理",
    ]


def verify(province: str, subject: str, user_rank: int, major_name: str, major_cat: str,
           view: str, reason: str, bias: str,
           view_source: str = "", evidence_grade: str = "", source_url: str = "") -> dict:
    """交叉核验单个专业（语义分层版，S2 起接入真实校线）。"""
    ana = analyze_major(province, subject, user_rank, major_name, major_cat)
    if not ana["ok"]:
        return ana

    best = ana["best_reachable"]
    reach = _reachability(view, best["tier"] if best else None)
    reach_msg = _reachability_message(major_name, view, best, reach)

    # S2：真实校线可达性 + 可计算的 alignment（证据一致性=可及性核验）
    real = real_reachability(province, subject, user_rank)
    alignment, alignment_label, alignment_msg, raw_records, alignment_basis = _alignment_of(view, real)

    sources = _build_sources(major_name, view_source, evidence_grade, source_url, real)

    suggestions = _suggestions(view, bias, reach)
    return _pack(province, subject, user_rank, major_name, view, reason, bias, ana,
                 reach, reach_msg, alignment, alignment_label, alignment_msg, suggestions,
                 view_source, evidence_grade, source_url, real, sources, raw_records,
                 alignment_basis)


# ---------------------------------------------------------------- 真实校线可达性（S2）

_ELITE_CACHE = None


def _elite_sets() -> tuple[set, set]:
    global _ELITE_CACHE
    if _ELITE_CACHE is None:
        try:
            s985 = set(_repo.elite_names("985"))
            s211 = set(_repo.elite_names("211"))
        except Exception:
            s985, s211 = set(), set()
        _ELITE_CACHE = (s985, s211)
    return _ELITE_CACHE


def real_reachability(province: str, subject: str, user_rank: int) -> dict | None:
    """查询真实校线（掌上高考 2025 真实抓取 + 考试院官方表，若已导入）下候选位次的可及性。

    数据权威性（S5-A）：
    - 同时消费 ``official`` 与 ``estimated_real`` 两种来源，优先用官方数据；
    - 每条 ``raw_record`` 都带 ``data_source`` 与 ``source_label``（官方 / 真实抓取），
      前端据此显式标注，做到「真实抓取 ≠ 官方」的诚实区分；
    - 返回 ``data_source_summary``（各来源行数）与 ``grade``，供健康上报与权威性横幅。

    返回 None 表示该 (省/科类) 暂无任何校线数据（单侧降级）。
    返回的 ``reachable`` 为该省/科类下「位次 <= 候选位次」的真实院校清单（按门槛位次升序，
    即最容易触及的排最前），每条带原始数据链接 ``source_url``，保证"原始数据点击可达"。
    """
    s985, s211 = _elite_sets()
    with session_scope() as s:
        rows = s.scalars(
            select(SchoolLine).where(
                SchoolLine.province == province, SchoolLine.subject == subject)
        ).all()
        if not rows:
            return None
        src_counts = {"official": 0, "estimated_real": 0, "other": 0}
        reachable = []
        for r in rows:
            ds = r.data_source or "estimated_real"
            src_counts[ds if ds in src_counts else "other"] += 1
            if not r.min_rank or r.min_rank < user_rank:
                continue
            tier = "985" if r.university in s985 else ("211" if r.university in s211 else "")
            reachable.append({
                "university": r.university, "min_rank": r.min_rank, "min_score": r.min_score,
                "year": r.year, "batch": r.batch, "tier": tier,
                "source_url": r.source_url,
                "data_source": ds,
                "source_label": "官方" if ds == "official" else "真实抓取",
            })
    reachable.sort(key=lambda x: (x["data_source"] != "official", x["min_rank"]))
    # S7-C：样本量（校线条数 / 覆盖院校数）是「敢不敢下判断」的前提，随结果一并返回
    total_schools = len({r.university for r in rows})
    reachable_schools = len({r["university"] for r in reachable})
    tiers = {"985": 0, "211": 0, "benke": 0, "zhuanke": 0}
    for r in reachable:
        if r["tier"] == "985":
            tiers["985"] += 1
        elif r["tier"] == "211":
            tiers["211"] += 1
        elif (r["batch"] or "").find("专") >= 0:
            tiers["zhuanke"] += 1
        else:
            tiers["benke"] += 1
    # 优先用官方数据作为「最易触及」展示；没有官方则退到真实抓取
    best = reachable[0] if reachable else None
    official = src_counts["official"]
    estimated = src_counts["estimated_real"]
    grade = "official" if official else ("mixed" if (official and estimated) else "estimated_real")
    return {
        "has_data": True, "province": province, "subject": subject,
        "total_lines": len(rows), "reachable": len(reachable),
        "total_schools": total_schools, "reachable_schools": reachable_schools,
        "tiers": tiers, "best": best, "reachable_sample": reachable[:10],
        "data_source_summary": {
            "official": official, "estimated_real": estimated,
            "other": src_counts["other"], "total": len(rows),
            # S9-D：官方覆盖专业组占比，避免把「少数 official 行」误读成「数据都官方」
            "official_coverage": SL.official_coverage(),
        },
        "grade": grade,
        "upstream": "掌上高考 gaokao.cn（2025 真实录取记录，经 gaokao-admission-crawler 整理，MIT）"
                    + ("；含考试院官方投档表（official）" if official else ""),
    }


# S7-C 证据门槛：低于该样本量时不给「支持 / 反驳」的强判断，单侧降级为 unverified。
# 一条校线就敢说「数据支持观点」，是把对置版式变成了无信息放大——那句判断其实什么都没证明。
# S8-B：门槛按真实分布分层校准（见 scripts/calibrate_evidence_gate.py 的实测分布）。
# 三档：
#   none —— 近乎没样本，完全不下判断；
#   thin —— 有样本但不够厚，只给方向性事实，不判「支持 / 反驳」；
#   full —— 够厚，允许判断。
MIN_EVIDENCE_LINES = 10      # 一般强判断：至少这么多条真实校线（S7-C 原始值，实测最低 46 条）
MIN_EVIDENCE_SCHOOLS = 5     # 且至少覆盖这么多所不同院校（实测最低 46 所）
MIN_THIN_LINES = 3           # 低于此视为「近乎无样本」
MIN_THIN_SCHOOLS = 2
# 「够不到任何院校」是**全称否定**断言，比「够得到某一所」（存在性断言）需要更多证据：
# 少几条校线就能证明「有一所够得到」，但要说「所有都够不到」必须覆盖足够多。
MIN_REFUTE_LINES = 20
MIN_REFUTE_SCHOOLS = 10
GRADE_LABEL = {"official": "考试院官方", "mixed": "官方 + 真实抓取", "estimated_real": "真实抓取（非官方）"}
BAND_LABEL = {"full": "样本充足（可判断）", "thin": "样本偏薄（仅方向性提示）",
              "none": "样本近乎为零（不下判断）"}


def _evidence_band(real: dict) -> tuple[str, dict]:
    """证据分层（S8-B）：返回 ``(band, basis)``，band ∈ {none, thin, full}。

    与 S7-C 的布尔门槛相比，这里多做两件事：
      1. 把「不足」再切成 none / thin —— 偏薄时给出方向性事实，而不是一句「不下判断」了事；
      2. 对「够不到任何」这类全称否定额外设更高门槛（``refute_gate_passed``）。
    """
    lines = int(real.get("total_lines") or 0)
    schools = int(real.get("total_schools") or 0)
    if lines < MIN_THIN_LINES or schools < MIN_THIN_SCHOOLS:
        band = "none"
    elif lines >= MIN_EVIDENCE_LINES and schools >= MIN_EVIDENCE_SCHOOLS:
        band = "full"
    else:
        band = "thin"
    basis = {
        "total_lines": lines, "min_lines": MIN_EVIDENCE_LINES,
        "total_schools": schools, "min_schools": MIN_EVIDENCE_SCHOOLS,
        "reachable": int(real.get("reachable") or 0),
        "reachable_schools": int(real.get("reachable_schools") or 0),
        "grade": real.get("grade", ""),
        "grade_label": GRADE_LABEL.get(real.get("grade", ""), real.get("grade", "")),
        "gate_passed": band == "full",           # 保持向后兼容（S7-C 语义）
        "band": band, "band_label": BAND_LABEL[band],
        "refute_gate_passed": lines >= MIN_REFUTE_LINES and schools >= MIN_REFUTE_SCHOOLS,
        "min_refute_lines": MIN_REFUTE_LINES, "min_refute_schools": MIN_REFUTE_SCHOOLS,
        "thresholds": {"thin": [MIN_THIN_LINES, MIN_THIN_SCHOOLS],
                       "full": [MIN_EVIDENCE_LINES, MIN_EVIDENCE_SCHOOLS],
                       "refute": [MIN_REFUTE_LINES, MIN_REFUTE_SCHOOLS]},
    }
    return band, basis


def _evidence_gate(real: dict) -> tuple[bool, dict]:
    """证据是否足以支撑「支持 / 反驳」的强判断（S7-C 语义，兼容保留）。"""
    band, basis = _evidence_band(real)
    return band == "full", basis


def gate_profile() -> dict:
    """门槛校准台账（S8-B）：当前阈值 + 全库各 (省/科类) 落在哪一档的统计。

    用来回答「10/5 到底合不合理」：把真实分布摆出来，而不是拍脑袋。
    """
    with session_scope() as s:
        rows = s.execute(select(SchoolLine.province, SchoolLine.subject,
                                SchoolLine.university)).all()
    agg: dict[tuple, dict] = {}
    for p, subj, uni in rows:
        key = (p, subj)
        item = agg.setdefault(key, {"lines": 0, "schools": set()})
        item["lines"] += 1
        item["schools"].add(uni)
    bands = {"full": 0, "thin": 0, "none": 0}
    detail = []
    for (p, subj), item in sorted(agg.items()):
        lines, schools = item["lines"], len(item["schools"])
        if lines < MIN_THIN_LINES or schools < MIN_THIN_SCHOOLS:
            band = "none"
        elif lines >= MIN_EVIDENCE_LINES and schools >= MIN_EVIDENCE_SCHOOLS:
            band = "full"
        else:
            band = "thin"
        bands[band] += 1
        detail.append({"province": p, "subject": subj, "lines": lines,
                       "schools": schools, "band": band,
                       "refute_ok": lines >= MIN_REFUTE_LINES and schools >= MIN_REFUTE_SCHOOLS})
    return {"thresholds": {"thin": [MIN_THIN_LINES, MIN_THIN_SCHOOLS],
                           "full": [MIN_EVIDENCE_LINES, MIN_EVIDENCE_SCHOOLS],
                           "refute": [MIN_REFUTE_LINES, MIN_REFUTE_SCHOOLS]},
            "combos": len(agg), "bands": bands,
            "min_lines_observed": min((d["lines"] for d in detail), default=0),
            "min_schools_observed": min((d["schools"] for d in detail), default=0),
            "detail": detail}


def _alignment_of(view: str, real: dict | None):
    """可计算的 alignment（证据一致性 = 可及性核验）+ S7-C 证据门槛。

    设计红线：数据（校线）只能核验"能否读到"，**不能**核验专业就业价值本身。
    所有文案显式声明这一点。

    返回 ``(alignment, label, message, raw_records, basis)``，``basis`` 写清判断依据
    （校线条数 / 覆盖院校数 / 数据等级 / 是否过门槛），让「为什么是这个结论」可查。
    """
    empty_basis = {"total_lines": 0, "min_lines": MIN_EVIDENCE_LINES, "total_schools": 0,
                   "min_schools": MIN_EVIDENCE_SCHOOLS, "reachable": 0, "reachable_schools": 0,
                   "grade": "", "grade_label": "", "gate_passed": False,
                   "band": "none", "band_label": BAND_LABEL["none"], "refute_gate_passed": False}
    if real is None or not real.get("has_data"):
        return (ALIGNMENT_UNVERIFIED, ALIGNMENT_LABEL[ALIGNMENT_UNVERIFIED],
                "该 (省/科类) 暂无真实校线佐证，无法核验可及性；以上为批次门槛估算的可及性提示，"
                "不等于数据支持或反驳该观点。", [], empty_basis)

    band, basis = _evidence_band(real)
    grade_note = f"；数据等级：{basis['grade_label']}" if basis["grade_label"] else ""

    if band == "none":
        # 样本近乎为零：连方向性事实都谈不上，只说明为什么不判。
        return (ALIGNMENT_UNVERIFIED, ALIGNMENT_LABEL[ALIGNMENT_UNVERIFIED],
                f"该 (省/科类) 只有 {basis['total_lines']} 条真实校线、覆盖 {basis['total_schools']} 所院校，"
                f"低于最低观察量（≥{MIN_THIN_LINES} 条 / ≥{MIN_THIN_SCHOOLS} 所）。样本近乎为零时"
                "任何判断都没有信息量，因此这里**不下判断**，仅提示可及性参考。", [], basis)

    if band == "thin":
        # S8-B：偏薄档——不下强判断，但把「看到的事实」摆出来，而不是一句「不知道」了事。
        seen = ""
        if real.get("reachable"):
            b = real["best"]
            seen = (f"已收录的校线里，最容易触及的是 {b['university']}（门槛位次 {b['min_rank']}），"
                    f"共 {basis['reachable']} 条记录可及——这是事实陈述，不作为「支持该观点」的判断。")
        else:
            seen = ("已收录的校线里没有一所的门槛位次在你之后，但这**不等于**你够不到所有院校。")
        return (ALIGNMENT_UNVERIFIED, ALIGNMENT_LABEL[ALIGNMENT_UNVERIFIED],
                f"该 (省/科类) 只有 {basis['total_lines']} 条真实校线、覆盖 {basis['total_schools']} 所院校，"
                f"未达判定门槛（≥{MIN_EVIDENCE_LINES} 条 / ≥{MIN_EVIDENCE_SCHOOLS} 所），属「样本偏薄」。"
                f"{seen}数据侧**不下判断**，仅作方向性参考{grade_note}。", [], basis)

    if not real.get("reachable"):
        # 「够不到任何」是全称否定，需要比「够得到某一所」更厚的样本才敢说。
        if not basis["refute_gate_passed"]:
            return (ALIGNMENT_UNVERIFIED, ALIGNMENT_LABEL[ALIGNMENT_UNVERIFIED],
                    f"已收录的 {basis['total_lines']} 条真实校线里，没有一所的门槛位次在你之后。"
                    f"但「所有院校都够不到」是全称否定，本项目要求 ≥{MIN_REFUTE_LINES} 条 / "
                    f"≥{MIN_REFUTE_SCHOOLS} 所才敢这么断言（当前 {basis['total_schools']} 所），"
                    f"因此这里**不下「够不到」的判断**{grade_note}。", [], basis)
        msg = ("真实校线显示：你的位次够不到该 (省/科类) 下任何真实院校开设的项目层次。"
               "这是**可及性**层面的事实，不代表该专业「没有价值」——只是以你当前位次，"
               f"数据侧看不到你能踏入开设它的院校{grade_note}。")
        return "refuted", ALIGNMENT_LABEL["refuted"], msg, [], basis
    best = real["best"]
    best_tier = best["tier"]
    if best_tier in ("985", "211"):
        level_note = f"可触及 {best_tier} 层次院校（如 {best['university']}，门槛位次 {best['min_rank']}）"
    elif real["tiers"]["benke"]:
        level_note = f"可触及普通本科院校（最易 {best['university']}，门槛位次 {best['min_rank']}）"
    else:
        level_note = f"仅可触及专科层次（最易 {best['university']}，门槛位次 {best['min_rank']}）"
    msg = (f"真实校线显示：{level_note}。数据侧仅核验**可及性**（你能否读到开设该专业的院校），"
           "**不能**核验专业就业价值本身；以下为事实陈述，观点是否成立仍须结合就业判断"
           f"{grade_note}。")
    return "supported", ALIGNMENT_LABEL["supported"], msg, real["reachable_sample"], basis


def _build_sources(major_name, view_source, evidence_grade, source_url, real) -> list:
    """对置版式双来源：观点来源 + 数据来源。"""
    opinion = {
        "kind": "opinion", "label": "观点来源",
        "source": view_source or "就业确定性优先（观点整理）",
        "evidence_grade": evidence_grade or "",
        "url": source_url or "",
        "note": "观点为「值不值」的价值主张，需结合就业判断；非数据可证伪。",
    }
    if real and real.get("has_data"):
        summ = real.get("data_source_summary", {}) or {}
        official = summ.get("official", 0)
        estimated = summ.get("estimated_real", 0)
        if official and estimated:
            auth_note = (f"共 {real['total_lines']} 条，其中官方 {official} 条、真实抓取 {estimated} 条；"
                        "官方数据来自考试院投档原表，其余为掌上高考 2025 真实抓取（estimated_real）。")
        elif official:
            auth_note = (f"共 {real['total_lines']} 条，全部为考试院官方投档原表（official）；"
                        "以各省考试院公布为准。")
        else:
            auth_note = (f"真实录取记录 {real['total_lines']} 条，其中你的位次可触及 {real['reachable']} 条；"
                        "全部来自掌上高考 2025 真实抓取（estimated_real），非考试院官方发布。"
                        "官方性升级需在管理端「校线导入」上传各省考试院投档原表。")
        data = {
            "kind": "data", "label": "数据来源",
            "source": real["upstream"],
            "url": real["best"]["source_url"] if real.get("best") else "",
            "note": auth_note,
            "reachable": real["reachable"], "tiers": real["tiers"],
            "data_source_summary": summ,
            "grade": real.get("grade", "estimated_real"),
        }
    else:
        data = {
            "kind": "data", "label": "数据来源",
            "source": "（该省/科类暂无真实校线，单侧降级）",
            "url": "", "note": "未导入真实校线，无法展示数据侧。", "reachable": 0, "tiers": {},
        }
    return [opinion, data]


MAX_BATCH = 20


def verify_major_entry(province, subject, user_rank, major) -> dict:
    """按专业条目（content.json 里的 dict）执行一次核验。"""
    return verify(
        province=province, subject=subject, user_rank=user_rank,
        major_name=major["name"], major_cat=major["cat"], view=major["view"],
        reason=major["reason"], bias=major["bias"],
        view_source=major.get("view_source", ""),
        evidence_grade=major.get("evidence_grade", ""),
        source_url=major.get("source_url", ""),
    )


def verify_many(province: str, subject: str, user_rank: int, majors: list[dict]) -> dict:
    """批量交叉核验（P1→P2 打通）：一次算出多个专业的 可及性 判定。

    返回按「不可及 → 仅够低层次 → 可达一本 → 可达高层次」排序的结果列表 +
    可及性分布计数，供前端一次渲染（风险优先，先看最受限项）。
    """
    err = validate_user_rank(user_rank)
    if err:
        return {"ok": False, "error": err}
    if not majors:
        return {"ok": False, "error": "未提供待核验专业"}

    results, missing = [], []
    for m in majors:
        r = verify_major_entry(province, subject, user_rank, m)
        if not r.get("ok"):
            missing.append({"major": m["name"], "error": r.get("error", "核验失败")})
            continue
        results.append(r)

    # S3：批量排序 —— 先按 alignment（反驳→无证据→支持，风险优先），再按 reachability
    ALIGN_ORDER = {"refuted": 0, "unverified": 1, "supported": 2}
    results.sort(key=lambda r: (ALIGN_ORDER.get(r["alignment"], 9),
                                REACHABILITY_ORDER.get(r["reachability"], 9), r["major"]))
    summary = {"total": len(results), "out_of_reach": 0, "low": 0, "mid": 0, "high": 0,
               "alignment": {"refuted": 0, "unverified": 0, "supported": 0}}
    for r in results:
        summary[r["reachability"]] = summary.get(r["reachability"], 0) + 1
        summary["alignment"][r["alignment"]] = summary["alignment"].get(r["alignment"], 0) + 1

    return {
        "ok": True,
        "province": province, "subject": subject, "user_rank": user_rank,
        "count": len(results),
        "summary": summary,
        "results": results,
        "missing": missing,
        "data_source": results[0]["data_source"] if results else "",
    }


def _pack(province, subject, user_rank, major_name, view, reason, bias, ana,
          reach, reach_msg, alignment, alignment_label, alignment_msg, suggestions,
          view_source, evidence_grade, source_url, real, sources, raw_records,
          alignment_basis=None) -> dict:
    return {
        "ok": True,
        "province": province, "subject": subject, "user_rank": user_rank,
        "major": major_name,
        "view": view, "view_label": VIEW_LABEL.get(view, view),
        "view_source": view_source, "evidence_grade": evidence_grade, "source_url": source_url,
        "reason": reason, "bias": bias,
        "best_reachable": ana["best_reachable"],
        "tiers": ana["tiers"],
        "reachability": reach,
        "reachability_label": REACHABILITY_LABEL[reach],
        "reachability_message": reach_msg,
        "alignment": alignment,
        "alignment_label": alignment_label,
        "alignment_message": alignment_msg,
        # S7-C：判断依据可查——样本量是否过门槛、数据等级是什么
        "alignment_basis": alignment_basis or {},
        "message": reach_msg,
        "suggestions": suggestions,
        "data_source": ana["data_source"],
        "reachable_tier": ana.get("reachable_tier"),
        "reachable_tier_schools": ana.get("reachable_tier_schools", []),
        "reachable_tier_school_count": ana.get("reachable_tier_school_count", 0),
        # S2：真实校线 + 双来源 + 原始数据点击可达
        "real_data": real,
        "sources": sources,
        "raw_records": raw_records,
        # S5-A：院校级投档线的权威等级（official / mixed / estimated_real）
        "school_line_grade": (real or {}).get("grade", ""),
        "school_line_summary": (real or {}).get("data_source_summary", {}),
    }
