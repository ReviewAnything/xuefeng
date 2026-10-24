"""数据质量与体检（P2）：准确性保障体系。

三块能力：
1. **位次交叉校验**：official 行的 ``min_score`` 经该省当年一分一段表反查位次，
   与原表 ``min_rank`` 比对，偏差超阈值即告警（不阻断落库）——入口校验挡住
   「格式错」，交叉校验挡住「转录错」。
2. **跨年突变检测**：同校同专业组相邻两年位次变化超阈值时列出清单，
   可能是真波动（扩招/改名）也可能是转录错误，供人工复核。
3. **数据体检报告**：官方覆盖、溯源台账、落地区待办、交叉校验复检、
   跨年突变、种子一致性，一键汇总成一份可操作的运维报告。

诚实边界：一分一段表本身也是转录数据，交叉校验通过 ≠ 绝对正确；
它只回答「两个独立转录是否互相印证」。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from db.database import session_scope
from db.models import SchoolLine
from services import rank_tables as RT

# 偏差阈值：一分一段表是「分数→累计人数」，投档位次应落在同分累计附近；
# 超过 25% 大概率是转录错列（如把「最高分位次」抄成「最低分位次」）。
CROSS_CHECK_MAX_DEVIATION = 0.25
# 跨年突变阈值：相邻两年位次变化超 50% 列入复核清单。
YOY_MAX_CHANGE = 0.5


def _expected_rank(year: int, province: str, subject: str, score: int) -> int | None:
    """分数 → 该省当年一分一段表的本科档累计位次；表缺失返回 None。"""
    hit = RT.lookup(int(year), province, subject, int(score))
    if not hit:
        return None
    return hit.get("cum_ben") or hit.get("cum_zhuan")


def cross_check(rec: dict) -> dict | None:
    """单行交叉校验。返回告警 dict；无表可比或偏差在阈值内返回 None。"""
    score = rec.get("min_score") or 0
    rank = rec.get("min_rank") or 0
    if not score or not rank:
        return None
    expected = _expected_rank(rec.get("year"), rec.get("province", ""),
                              rec.get("subject", ""), score)
    if not expected:
        return None
    deviation = abs(expected - rank) / max(1, expected)
    if deviation <= CROSS_CHECK_MAX_DEVIATION:
        return None
    return {"expected_rank": expected, "min_rank": int(rank),
            "deviation": round(deviation, 4)}


def annotate_cross_check(records: list[dict]) -> dict:
    """对可落库行批量交叉校验，把告警写进行备注（「疑点留在数据里」）。

    返回 ``{"checked": 可校验行数, "warnings": 告警明细}``；
    commit 路径下备注随行落库，dry-run 路径仅供预览，不落库。
    """
    warnings: list[dict] = []
    checked = 0
    for rec in records or []:
        w = cross_check(rec)
        if w is None:
            continue
        checked += 1
        item = {"year": rec.get("year"), "province": rec.get("province"),
                "subject": rec.get("subject"), "university": rec.get("university"), **w}
        warnings.append(item)
        note = rec.get("note") or ""
        rec["note"] = (note + "；" if note else "") + (
            f"位次交叉校验：按 {rec.get('year')} 年一分一段表 {rec.get('min_score')} 分"
            f"≈{w['expected_rank']} 位，原表位次 {rec.get('min_rank')} "
            f"偏差 {w['deviation'] * 100:.0f}%，需人工复核")
    return {"checked": checked, "warnings": warnings}


def year_over_year_anomalies(threshold: float = YOY_MAX_CHANGE) -> list[dict]:
    """同校同专业组相邻两年位次突变清单（按变化幅度降序）。"""
    with session_scope() as s:
        rows = s.execute(
            select(SchoolLine.province, SchoolLine.subject, SchoolLine.university,
                   SchoolLine.group_code, SchoolLine.year, SchoolLine.min_rank,
                   SchoolLine.data_source)
            .where(SchoolLine.min_rank > 0)
            .order_by(SchoolLine.province, SchoolLine.subject, SchoolLine.university,
                      SchoolLine.group_code, SchoolLine.year)).all()
    series: dict[tuple, list] = {}
    for prov, subj, uni, grp, year, rank, ds in rows:
        series.setdefault((prov, subj, uni, grp), []).append((int(year), int(rank), ds or ""))
    anomalies: list[dict] = []
    for (prov, subj, uni, grp), items in series.items():
        items.sort()
        for (y0, r0, ds0), (y1, r1, ds1) in zip(items, items[1:]):
            if y1 - y0 != 1:
                continue  # 只看相邻年：隔年对比受改革/批次合并干扰，不可直接比
            change = abs(r1 - r0) / max(1, r0)
            if change <= threshold:
                continue
            anomalies.append({
                "province": prov, "subject": subj, "university": uni, "group_code": grp,
                "from_year": y0, "from_rank": r0, "to_year": y1, "to_rank": r1,
                "change_pct": round(change * 100, 1), "sources": f"{ds0}→{ds1}",
            })
    anomalies.sort(key=lambda a: -a["change_pct"])
    return anomalies


def health_report() -> dict:
    """一键体检：官方覆盖 / 溯源台账 / 落地区待办 / 交叉校验复检 / 跨年突变 / 种子一致性。"""
    from services import school_lines as SL  # 局部导入避免环

    counts = SL.source_counts()

    # official 行全量交叉校验复检（只读，不改备注）
    with session_scope() as s:
        rows = s.execute(
            select(SchoolLine.year, SchoolLine.province, SchoolLine.subject,
                   SchoolLine.university, SchoolLine.min_score, SchoolLine.min_rank)
            .where(SchoolLine.data_source == "official")).all()
    checked = warnings = 0
    samples: list[dict] = []
    for year, prov, subj, uni, score, rank in rows:
        w = cross_check({"year": year, "province": prov, "subject": subj,
                         "min_score": score, "min_rank": rank})
        if w is None:
            continue
        checked += 1
        item = {"year": year, "province": prov, "subject": subj, "university": uni, **w}
        if len(samples) < 20:
            samples.append(item)
        warnings += 1

    landing = SL.official_landing_rows()
    anomalies = year_over_year_anomalies()
    return {
        "school_lines": counts,
        "official_sources": SL.official_registry(),
        "official_landing": {
            "dir": landing["dir"], "dir_exists": landing["dir_exists"],
            "files": landing["files"], "accepted": landing["accepted_count"],
            "rejected": landing["rejected_count"],
            "provenance_warnings": landing["provenance_warnings"],
        },
        "cross_check": {
            "threshold_pct": round(CROSS_CHECK_MAX_DEVIATION * 100),
            "official_rows": len(rows), "checked": checked, "warnings": warnings,
            "samples": samples,
            "note": "checked=有一分一段表可比的行数；无表可比（年份/省份未同步）不计数",
        },
        "year_over_year_anomalies": {
            "threshold_pct": round(YOY_MAX_CHANGE * 100),
            "count": len(anomalies), "samples": anomalies[:50],
        },
        "seed": SL.verify_seed(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
