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


def _expected_rank(year: int, province: str, subject: str, score: int,
                   batch: str = "") -> int | None:
    """分数 → 该省当年一分一段表的累计位次；表缺失返回 None。

    档位选择（审核局限②修复）：专科批校线用 ``cum_zhuan``（专科档累计），
    其余（默认）用 ``cum_ben``（本科档累计）。双档表两列口径不同，拿专科分数
    反查本科档累计会系统性误报；单档省两列相同，无影响。
    """
    hit = RT.lookup(int(year), province, subject, int(score))
    if not hit:
        return None
    if "专" in (batch or ""):
        return hit.get("cum_zhuan") or hit.get("cum_ben")
    return hit.get("cum_ben") or hit.get("cum_zhuan")


def cross_check(rec: dict) -> dict | None:
    """单行交叉校验。返回告警 dict；无表可比或偏差在阈值内返回 None。"""
    score = rec.get("min_score") or 0
    rank = rec.get("min_rank") or 0
    if not score or not rank:
        return None
    expected = _expected_rank(rec.get("year"), rec.get("province", ""),
                              rec.get("subject", ""), score,
                              batch=rec.get("batch") or "")
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


def control_line_violations() -> list[dict]:
    """M15 型硬约束体检：投档分低于该省当年对应批次省控线的行（全来源覆盖）。

    口径（保守，宁漏勿误）：
    - 批次判定：``batch`` 含「专」→ 对比专科档控线；含「本」→ 对比本科档控线里
      **最低**的一档（本科录取不可能低于全省最低本科线）；batch 缺失或两类都不含 → 跳过；
    - 科类匹配：与省控线科类键精确一致才比，匹配不上（如老高考文科 vs 新高考历史类
      键名差异）→ 跳过，不臆造；
    - 该年省控线缺失 → 跳过。
    """
    from services import control_lines as CL  # 局部导入避免环

    doc_years = CL.years()
    by_year: dict[int, dict] = {}
    for y in doc_years:
        r = CL.get_control_lines(int(y))
        if r.get("ok"):
            by_year[int(y)] = r["data"]

    def _lowest(block: dict, keyword: str) -> int | None:
        scores = [v.get("score") for k, v in (block or {}).items()
                  if keyword in k and isinstance(v, dict)]
        scores = [int(s) for s in scores if s is not None]
        return min(scores) if scores else None

    with session_scope() as s:
        rows = s.execute(
            select(SchoolLine.year, SchoolLine.province, SchoolLine.subject,
                   SchoolLine.university, SchoolLine.batch, SchoolLine.min_score,
                   SchoolLine.data_source)
            .where(SchoolLine.min_score > 0)).all()

    out: list[dict] = []
    for year, prov, subj, uni, batch, score, ds in rows:
        year, score = int(year), int(score)
        blocks = by_year.get(year, {}).get(prov)
        if not blocks:
            continue
        block = blocks.get(subj)
        if block is None:  # 科类键精确匹配不上 → 不比（保守）
            continue
        b = batch or ""
        if "专" in b:
            control = _lowest(block, "专")
        elif "本" in b:
            control = _lowest(block, "本")
        else:
            continue
        if control is None or score >= control:
            continue
        out.append({"year": year, "province": prov, "subject": subj,
                    "university": uni, "batch": b, "min_score": score,
                    "control_line": control, "data_source": ds or "estimated_real"})
    out.sort(key=lambda v: v["min_score"] - v["control_line"])
    return out


def health_report() -> dict:
    """一键体检：官方覆盖 / 溯源台账 / 落地区待办 / 交叉校验复检 / 跨年突变 / 种子一致性。"""
    from services import school_lines as SL  # 局部导入避免环

    counts = SL.source_counts()

    # 交叉校验复检（只读，不改备注）。审核局限①修复：扩展到**全部来源**——
    # 库内 99.9% 是 estimated_real，只查 official 会让体检抓不到主要数据面的问题。
    with session_scope() as s:
        rows = s.execute(
            select(SchoolLine.year, SchoolLine.province, SchoolLine.subject,
                   SchoolLine.university, SchoolLine.batch, SchoolLine.min_score,
                   SchoolLine.min_rank, SchoolLine.data_source)).all()
    checked = warnings = 0
    by_source: dict[str, dict] = {}
    samples: list[dict] = []
    for year, prov, subj, uni, batch, score, rank, ds in rows:
        w = cross_check({"year": year, "province": prov, "subject": subj, "batch": batch,
                         "min_score": score, "min_rank": rank})
        if w is None:
            continue
        checked += 1
        key = ds or "estimated_real"
        agg = by_source.setdefault(key, {"rows": 0, "warnings": 0})
        agg["warnings"] += 1
        item = {"year": year, "province": prov, "subject": subj, "university": uni, **w}
        if len(samples) < 20:
            samples.append(item)
        warnings += 1
    total_by_source: dict[str, int] = {}
    for _, _, _, _, _, _, _, ds in rows:
        k = ds or "estimated_real"
        total_by_source[k] = total_by_source.get(k, 0) + 1
    for k, agg in by_source.items():
        agg["rows"] = total_by_source.get(k, 0)

    landing = SL.official_landing_rows()
    anomalies = year_over_year_anomalies()
    violations = control_line_violations()
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
            "rows_total": len(rows), "checked": checked, "warnings": warnings,
            "by_source": by_source,
            "samples": samples,
            "note": "checked=有一分一段表可比且偏差超阈值的行数；无表可比（年份/省份未同步）不计数；覆盖全部数据来源",
        },
        "control_line_violations": {
            "count": len(violations), "samples": violations[:50],
            "note": "M15 型硬约束：投档分低于当年对应批次省控线的行（全来源），属确定性数据错误",
        },
        "year_over_year_anomalies": {
            "threshold_pct": round(YOY_MAX_CHANGE * 100),
            "count": len(anomalies), "samples": anomalies[:50],
        },
        "seed": SL.verify_seed(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
