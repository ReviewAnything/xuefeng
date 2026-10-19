"""数据版本管理：年度更新、单年补丁、校验、发布与回滚。

生命周期
--------
    draft ──validate──▶ validated ──publish──▶ published ──（新版本发布）──▶ archived
      ▲                                            │
      └──────────────── 补丁 / 回滚 ◀───────────────┘

- 每个 (数据集, 年份) 一个版本，多年数据并存于同一张表；
- 对外服务只读取「当前生效年份」settings.data_active_year；
- 任何写入都进 data_changes 审计表，支持按条回滚。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from db.database import session_scope
from db.models import AdmissionBaseline, DataChange, DataVersion, Setting
from db import repository as repo
from db import seed as seed_mod

DATASETS = ("admission", "universities", "content")

# 校验阈值
SCORE_MIN, SCORE_MAX = 0, 750
RANK_MIN, RANK_MAX = 1, 3_000_000
DRIFT_WARN_RATIO = 0.40      # 同比位次/分数波动超过 40% 告警
CARRIED_WARN_RATIO = 0.50    # 沿用往年值的行占比超过 50% 告警
SCHOOL_TIERS = ("985", "211")   # 院校层级（投档线口径与批次线不同，不做严格单调校验）


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _set_active(session, dataset: str, year: int) -> None:
    """在同一事务内切换生效年份（避免嵌套会话造成 SQLite 写锁）。"""
    key = f"data_active_year:{dataset}"
    row = session.get(Setting, key)
    if row:
        row.value = str(int(year))
    else:
        session.add(Setting(key=key, value=str(int(year))))


# ---------------------------------------------------------------- 基础查询

def active_year(dataset: str = "admission") -> int:
    return repo.active_year(dataset)


def list_versions(dataset: str = "admission") -> list[dict]:
    """版本列表（含行数、状态、校验结果、是否生效）。"""
    current = active_year(dataset)
    with session_scope() as s:
        rows = s.scalars(select(DataVersion).where(DataVersion.dataset == dataset)
                         .order_by(DataVersion.year.desc())).all()
        return [_version_dict(v, current) for v in rows]


def _version_dict(v: DataVersion, current_year: int) -> dict:
    try:
        check = json.loads(v.check_result or "{}")
    except (TypeError, ValueError):
        check = {}
    try:
        coverage = json.loads(v.coverage or "[]")
    except (TypeError, ValueError):
        coverage = []
    return {
        "id": v.id, "dataset": v.dataset, "year": v.year, "status": v.status,
        "revision": v.revision, "parent_year": v.parent_year,
        "row_count": v.row_count, "official_rows": v.official_rows,
        "carried_rows": v.carried_rows, "coverage": coverage,
        "coverage_count": len(coverage), "checksum": v.checksum[:12] if v.checksum else "",
        "note": v.note, "operator": v.operator,
        "is_active": v.year == current_year,
        "check": check,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
        "published_at": v.published_at.isoformat() if v.published_at else None,
    }


def version_detail(dataset: str, year: int) -> dict | None:
    with session_scope() as s:
        v = s.scalar(select(DataVersion).where(DataVersion.dataset == dataset,
                                               DataVersion.year == int(year)))
        return _version_dict(v, active_year(dataset)) if v else None


# ---------------------------------------------------------------- 年度更新

def clone_year(src_year: int, dst_year: int, dataset: str = "admission",
               operator: str = "system", note: str = "") -> dict:
    """以某一年为蓝本创建新年度草稿（年度更新第一步）。

    复制全部基线行到新年份；data_source 保留，carried 置 True 表示「沿用，待官方更新」。
    """
    src_year, dst_year = int(src_year), int(dst_year)
    if src_year == dst_year:
        return {"ok": False, "error": "源年份与目标年份不能相同"}
    with session_scope() as s:
        src_rows = s.scalars(select(AdmissionBaseline).where(
            AdmissionBaseline.year == src_year)).all()
        if not src_rows:
            return {"ok": False, "error": f"{src_year} 年没有可复制的基线数据"}
        existing = s.scalar(select(func.count()).select_from(AdmissionBaseline)
                            .where(AdmissionBaseline.year == dst_year))
        if existing:
            return {"ok": False, "error": f"{dst_year} 年数据已存在（{existing} 行），请先清理或使用补丁更新"}

        now = _now()
        for r in src_rows:
            s.add(AdmissionBaseline(
                year=dst_year, source_year=r.source_year or src_year,
                province=r.province, subject=r.subject, tier=r.tier,
                min_score=r.min_score, min_rank=r.min_rank,
                data_source=r.data_source, line=r.line, school=r.school,
                carried=True, source_url=r.source_url, updated_at=now))
        s.add(DataChange(dataset=dataset, year=dst_year, action="clone",
                         entity=f"{src_year} → {dst_year}",
                         old_value=str(src_year), new_value=str(dst_year),
                         reason=note or "年度更新：沿用上一年数据作为草稿",
                         operator=operator, created_at=now))
        s.flush()
        stat = seed_mod.register_version(s, dataset, dst_year, status="draft")
        v = s.scalar(select(DataVersion).where(DataVersion.dataset == dataset,
                                               DataVersion.year == dst_year))
        v.parent_year = src_year
        v.note = note or f"沿用 {src_year} 年数据，待官方数据回填"
        v.operator = operator
        s.flush()
    _invalidate()
    return {"ok": True, "year": dst_year, "from": src_year, "status": "draft", **(stat or {})}


# ---------------------------------------------------------------- 校验

def _tier_order() -> list[str]:
    return repo.tier_order() or ["985", "211", "一本", "二本", "专科"]


def validate_year(year: int, dataset: str = "admission") -> dict:
    """发布前校验：覆盖完整性、数值范围、层次单调性、来源可追溯、同比波动。"""
    year = int(year)
    tier_order = _tier_order()
    errors: list[dict] = []
    warnings: list[dict] = []

    with session_scope() as s:
        rows = s.scalars(select(AdmissionBaseline).where(AdmissionBaseline.year == year)).all()
        if not rows:
            return {"ok": False, "errors": [{"code": "EMPTY", "message": f"{year} 年没有任何基线数据"}],
                    "warnings": [], "stats": {"rows": 0}, "year": year}

        by_key: dict[tuple, dict] = {}
        provinces: set[str] = set()
        for r in rows:
            by_key[(r.province, r.subject, r.tier)] = r
            provinces.add(r.province)

        # 期望集合：优先取上一版本；没有则取本年自身的 (省, 科类) 组合
        prev_year = s.scalar(select(func.max(AdmissionBaseline.year))
                             .where(AdmissionBaseline.year < year))
        expected_pairs: set[tuple] = set()
        if prev_year:
            prev = s.execute(select(AdmissionBaseline.province, AdmissionBaseline.subject)
                             .where(AdmissionBaseline.year == prev_year)).all()
            expected_pairs = {(p, sub) for p, sub in prev}
        else:
            expected_pairs = {(r.province, r.subject) for r in rows}

        # R1 覆盖：省份 × 科类 × 批次
        missing = []
        for province, subject in sorted(expected_pairs):
            for tier in tier_order:
                if (province, subject, tier) not in by_key:
                    missing.append(f"{province}/{subject}/{tier}")
        if missing:
            errors.append({"code": "COVERAGE", "message": f"缺失 {len(missing)} 个（省×科类×批次）组合",
                           "sample": missing[:12]})

        # R2/R3/R4 数值与单调性
        range_bad, order_bad = [], []
        for (province, subject, tier), r in sorted(by_key.items()):
            if not (SCORE_MIN < r.min_score <= SCORE_MAX):
                range_bad.append(f"{province}/{subject}/{tier} 分数 {r.min_score}")
            if not (RANK_MIN <= r.min_rank <= RANK_MAX):
                range_bad.append(f"{province}/{subject}/{tier} 位次 {r.min_rank}")
        if range_bad:
            errors.append({"code": "RANGE", "message": f"{len(range_bad)} 行数值越界",
                           "sample": range_bad[:12]})

        order_warn = []
        for province, subject in sorted(expected_pairs):
            seq = [by_key.get((province, subject, t)) for t in tier_order]
            for i in range(len(seq) - 1):
                a, b = seq[i], seq[i + 1]
                if not a or not b:
                    continue
                inverted = (a.min_rank > b.min_rank) or (a.min_score < b.min_score)
                if not inverted:
                    continue
                detail = (f"{province}/{subject}: {a.tier} 位次 {a.min_rank}/分数 {a.min_score} "
                          f"与 {b.tier} 位次 {b.min_rank}/分数 {b.min_score} 倒挂")
                # 院校层级（985/211）投档线可能因中外合作 / 异地校区低于一本线，只提示；
                # 批次层级之间若来源一致则判定为错误，来源不同（官方与估算混用）仅提示。
                if a.tier in SCHOOL_TIERS or b.tier in SCHOOL_TIERS:
                    order_warn.append(detail + "（院校层级，常见于中外合作/异地校区）")
                elif a.data_source == b.data_source:
                    order_bad.append(detail)
                else:
                    order_warn.append(detail + f"（{a.data_source} 与 {b.data_source} 口径混用）")
        if order_bad:
            errors.append({"code": "MONOTONIC", "message": f"{len(order_bad)} 处批次门槛倒挂",
                           "sample": order_bad[:12]})
        if order_warn:
            warnings.append({"code": "ORDER_HINT", "message": f"{len(order_warn)} 处层次门槛需人工核对",
                             "sample": order_warn[:12]})

        # 同一 (省, 科类) 内官方与估算混用提示
        mixed = []
        for province, subject in sorted({(r.province, r.subject) for r in rows}):
            sources = {by_key[(province, subject, t)].data_source
                       for t in tier_order if (province, subject, t) in by_key}
            if "official" in sources and "estimated" in sources:
                mixed.append(f"{province}/{subject}")
        if mixed:
            warnings.append({"code": "MIXED_SOURCE",
                             "message": f"{len(mixed)} 个（省×科类）官方线与估算值混用，"
                                        "合并批次的省份需注意口径",
                             "sample": mixed[:12]})

        # R5 官方行必须可追溯
        no_source = [f"{r.province}/{r.subject}/{r.tier}" for r in rows
                     if r.data_source == "official" and not r.source_url]
        if no_source:
            errors.append({"code": "SOURCE_URL", "message": f"{len(no_source)} 行官方数据缺少来源链接",
                           "sample": no_source[:12]})

        # R6 同比波动告警
        drift = []
        if prev_year:
            prev_map = {(r.province, r.subject, r.tier): r for r in s.scalars(
                select(AdmissionBaseline).where(AdmissionBaseline.year == prev_year)).all()}
            for key, r in sorted(by_key.items()):
                p = prev_map.get(key)
                if not p or p.min_rank <= 0:
                    continue
                delta = abs(r.min_rank - p.min_rank) / p.min_rank
                if delta > DRIFT_WARN_RATIO:
                    drift.append(f"{r.province}/{r.subject}/{r.tier} 位次 {p.min_rank} → {r.min_rank}"
                                 f"（{delta * 100:.0f}%）")
        if drift:
            warnings.append({"code": "DRIFT", "message": f"{len(drift)} 行同比波动超过 "
                                                         f"{int(DRIFT_WARN_RATIO * 100)}%",
                             "sample": drift[:12]})

        # R7 沿用占比
        carried = sum(1 for r in rows if r.carried)
        if rows and carried / len(rows) > CARRIED_WARN_RATIO:
            warnings.append({"code": "CARRIED",
                             "message": f"{carried}/{len(rows)} 行仍是沿用往年值（{carried / len(rows) * 100:.0f}%），"
                                        "建议回填官方数据后再发布"})

        result = {
            "ok": not errors, "year": year, "dataset": dataset,
            "errors": errors, "warnings": warnings,
            "stats": {
                "rows": len(rows),
                "provinces": len(provinces),
                "official_rows": sum(1 for r in rows if r.data_source == "official"),
                "carried_rows": carried,
                "expected_pairs": len(expected_pairs),
                "compared_with": prev_year,
            },
            "validated_at": _now().isoformat(),
        }

        v = s.scalar(select(DataVersion).where(DataVersion.dataset == dataset, DataVersion.year == year))
        if v:
            v.check_result = json.dumps({"ok": result["ok"], "errors": errors, "warnings": warnings,
                                         "stats": result["stats"], "validated_at": result["validated_at"]},
                                        ensure_ascii=False)
            if v.status == "draft" and result["ok"]:
                v.status = "validated"
            v.updated_at = _now()
            s.flush()
        return result


# ---------------------------------------------------------------- 发布 / 回滚

def publish_year(year: int, dataset: str = "admission", operator: str = "system",
                 force: bool = False) -> dict:
    """发布某年份：校验通过后切换为生效版本，旧版本归档。"""
    year = int(year)
    check = validate_year(year, dataset)
    if not check["ok"] and not force:
        return {"ok": False, "error": "校验未通过，未发布", "check": check}
    now = _now()
    previous_year: int | None = None
    with session_scope() as s:
        v = s.scalar(select(DataVersion).where(DataVersion.dataset == dataset, DataVersion.year == year))
        if v is None:
            return {"ok": False, "error": f"{year} 年版本不存在"}
        prev_active = s.scalar(select(DataVersion).where(
            DataVersion.dataset == dataset, DataVersion.status == "published"))
        if prev_active and prev_active.year != year:
            previous_year = prev_active.year
            prev_active.status = "archived"
        v.status = "published"
        v.published_at = now
        v.operator = operator
        v.updated_at = now
        s.add(DataChange(dataset=dataset, year=year, action="publish",
                         entity=f"{dataset}/{year}",
                         old_value=str(previous_year) if previous_year else "",
                         new_value=str(year), operator=operator,
                         reason=f"发布为生效版本（校验{'通过' if check['ok'] else '未通过·强制发布'}）",
                         created_at=now))
        s.flush()
        _set_active(s, dataset, year)
    _invalidate()
    return {"ok": True, "year": year, "status": "published", "previous": previous_year,
            "check": {"ok": check["ok"], "warnings": check["warnings"]}}


def rollback(dataset: str, year: int, operator: str = "system", reason: str = "") -> dict:
    """回滚到指定年份（该年份数据必须仍存在）。"""
    year = int(year)
    now = _now()
    from_year: int | None = None
    with session_scope() as s:
        target = s.scalar(select(DataVersion).where(DataVersion.dataset == dataset,
                                                    DataVersion.year == year))
        if target is None:
            return {"ok": False, "error": f"{year} 年版本不存在，无法回滚"}
        count = int(s.scalar(select(func.count()).select_from(AdmissionBaseline)
                             .where(AdmissionBaseline.year == year)) or 0)
        if count == 0:
            return {"ok": False, "error": f"{year} 年没有任何数据行，无法回滚"}
        current = s.scalar(select(DataVersion).where(DataVersion.dataset == dataset,
                                                     DataVersion.status == "published"))
        if current and current.year != year:
            from_year = current.year
            current.status = "archived"
        target.status = "published"
        target.published_at = now
        target.operator = operator
        s.add(DataChange(dataset=dataset, year=year, action="rollback",
                         entity=f"{dataset}/{year}",
                         old_value=str(from_year) if from_year else "", new_value=str(year),
                         operator=operator, reason=reason or "回滚到历史版本", created_at=now))
        s.flush()
        _set_active(s, dataset, year)
    _invalidate()
    return {"ok": True, "year": year, "status": "published", "from": from_year, "rows": count}


# ---------------------------------------------------------------- 补丁与审计

PATCH_FIELDS = ("min_score", "min_rank", "data_source", "line", "school", "source_url", "carried")


def patch_baseline(row_id: int, payload: dict, operator: str = "system",
                   reason: str = "", publish: bool = False) -> dict:
    """修改单条基线（单年补丁），逐字段留痕。"""
    changes = []
    now = _now()
    with session_scope() as s:
        row = s.get(AdmissionBaseline, int(row_id))
        if row is None:
            return {"ok": False, "error": f"基线行 {row_id} 不存在"}
        for field in PATCH_FIELDS:
            if field not in payload or payload[field] is None:
                continue
            old = getattr(row, field)
            new = payload[field]
            if field in ("min_score", "min_rank", "carried"):
                new = int(new) if field != "carried" else bool(new)
            if old == new:
                continue
            setattr(row, field, new)
            row.updated_at = now
            s.add(DataChange(dataset="admission", year=row.year, action="patch",
                             entity=f"{row.province}/{row.subject}/{row.tier}",
                             field=field, old_value=str(old), new_value=str(new),
                             operator=operator, reason=reason, created_at=now))
            changes.append({"field": field, "old": old, "new": new})
        if not changes:
            return {"ok": True, "unchanged": True, "row_id": row_id}
        if payload.get("source_year"):
            row.source_year = int(payload["source_year"])
        if payload.get("carried") is None:
            row.carried = False   # 已被人工/脚本更新，不再是「沿用往年」
        s.flush()
        year, row_dict = row.year, _row_dict(row)
        stat = seed_mod.register_version(s, "admission", year)
        v = s.scalar(select(DataVersion).where(DataVersion.dataset == "admission",
                                               DataVersion.year == year))
        if v:
            v.revision = (v.revision or 1) + 1
            v.operator = operator
            v.updated_at = now
            s.flush()
    _invalidate()
    result = {"ok": True, "row_id": row_id, "changes": changes, "row": row_dict, **(stat or {})}
    if publish:
        result["publish"] = publish_year(year, operator=operator)
    return result


def create_baseline(payload: dict, operator: str = "system", reason: str = "") -> dict:
    """补录缺失的基线行（例如新增省份或新增科类）。"""
    required = ("year", "province", "subject", "tier", "min_score", "min_rank")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        return {"ok": False, "error": "缺少必填字段：" + "、".join(missing)}
    now = _now()
    with session_scope() as s:
        dup = s.scalar(select(AdmissionBaseline).where(
            AdmissionBaseline.year == int(payload["year"]),
            AdmissionBaseline.province == payload["province"],
            AdmissionBaseline.subject == payload["subject"],
            AdmissionBaseline.tier == payload["tier"]))
        if dup:
            return {"ok": False, "error": "该年份下已存在同 (省/科类/批次) 记录，请用补丁修改"}
        row = AdmissionBaseline(
            year=int(payload["year"]),
            source_year=int(payload.get("source_year") or payload["year"]),
            province=payload["province"], subject=payload["subject"], tier=payload["tier"],
            min_score=int(payload["min_score"]), min_rank=int(payload["min_rank"]),
            data_source=payload.get("data_source") or "estimated",
            line=payload.get("line") or "", school=payload.get("school") or "",
            source_url=payload.get("source_url") or "",
            carried=bool(payload.get("carried", False)), updated_at=now)
        s.add(row)
        s.add(DataChange(dataset="admission", year=row.year, action="create",
                         entity=f"{row.province}/{row.subject}/{row.tier}",
                         new_value=f"{row.min_score}/{row.min_rank}",
                         operator=operator, reason=reason or "补录缺失数据", created_at=now))
        s.flush()
        row_id, year, row_dict = row.id, row.year, _row_dict(row)
        stat = seed_mod.register_version(s, "admission", year)
    _invalidate()
    return {"ok": True, "row_id": row_id, "row": row_dict, **(stat or {})}


def _row_dict(r: AdmissionBaseline) -> dict:
    return {
        "id": r.id, "year": r.year, "source_year": r.source_year,
        "province": r.province, "subject": r.subject, "tier": r.tier,
        "min_score": r.min_score, "min_rank": r.min_rank,
        "data_source": r.data_source, "line": r.line, "school": r.school,
        "carried": bool(r.carried), "source_url": r.source_url,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def changes(dataset: str | None = None, year: int | None = None, limit: int = 50) -> list[dict]:
    with session_scope() as s:
        stmt = select(DataChange).order_by(DataChange.id.desc()).limit(min(int(limit), 200))
        if dataset:
            stmt = stmt.where(DataChange.dataset == dataset)
        if year:
            stmt = stmt.where(DataChange.year == int(year))
        return [{
            "id": c.id, "dataset": c.dataset, "year": c.year, "action": c.action,
            "entity": c.entity, "field": c.field, "old_value": c.old_value,
            "new_value": c.new_value, "reason": c.reason, "operator": c.operator,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        } for c in s.scalars(stmt).all()]


def undo_change(change_id: int, operator: str = "system") -> dict:
    """撤销单条字段级修改（按审计记录回滚）。"""
    now = _now()
    with session_scope() as s:
        c = s.get(DataChange, int(change_id))
        if c is None or c.action != "patch" or not c.field:
            return {"ok": False, "error": "仅支持撤销字段级补丁记录"}
        province, subject, tier = (c.entity.split("/") + ["", "", ""])[:3]
        row = s.scalar(select(AdmissionBaseline).where(
            AdmissionBaseline.year == c.year, AdmissionBaseline.province == province,
            AdmissionBaseline.subject == subject, AdmissionBaseline.tier == tier))
        if row is None:
            return {"ok": False, "error": "对应基线行已不存在"}
        old = getattr(row, c.field)
        new = int(c.old_value) if c.field in ("min_score", "min_rank") else c.old_value
        setattr(row, c.field, new)
        row.updated_at = now
        s.add(DataChange(dataset=c.dataset, year=c.year, action="patch", entity=c.entity,
                         field=c.field, old_value=str(old), new_value=str(new),
                         operator=operator, reason=f"撤销变更 #{change_id}", created_at=now))
        s.flush()
        row_dict = _row_dict(row)
        stat = seed_mod.register_version(s, "admission", row.year)
    _invalidate()
    return {"ok": True, "undone": change_id, "row": row_dict, **(stat or {})}


def pending_updates(year: int | None = None, dataset: str = "admission") -> dict:
    """待更新清单：沿用往年值的行（按省份聚合）。"""
    year = int(year or active_year(dataset))
    with session_scope() as s:
        rows = s.scalars(select(AdmissionBaseline).where(
            AdmissionBaseline.year == year, AdmissionBaseline.carried.is_(True))).all()
        by_province: dict[str, dict] = {}
        for r in rows:
            item = by_province.setdefault(r.province, {"province": r.province, "rows": 0,
                                                       "official": 0, "tiers": []})
            item["rows"] += 1
            item["official"] += 1 if r.data_source == "official" else 0
            item["tiers"].append(f"{r.subject}/{r.tier}")
        return {"ok": True, "year": year, "total": len(rows),
                "provinces": sorted(by_province.values(), key=lambda x: -x["rows"])}


def _invalidate() -> None:
    try:
        repo.invalidate()
        from services import admission as A

        A.invalidate_cache()
    except Exception:
        pass


def status(dataset: str = "admission") -> dict:
    """总览：生效年份、版本列表、待更新数量、最近变更。"""
    return {
        "ok": True,
        "dataset": dataset,
        "active_year": active_year(dataset),
        "versions": list_versions(dataset),
        "pending": pending_updates(dataset=dataset),
        "changes": changes(dataset, limit=10),
    }
