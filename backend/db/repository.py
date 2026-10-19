"""业务查询层：对上层（admission / 管理端）屏蔽 SQL 细节。

短 TTL 缓存保证高频核验请求不必每次查库，同时同步后最多 30s 自动生效。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from .database import DEFAULT_DB_PATH, session_scope
from .models import (AdmissionBaseline, EliteUniversity, Major, QueryEvent,
                     Resource, Setting, SyncJob, University)

_TTL = 30.0
_threshold_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_counts_cache: dict[str, tuple[float, dict]] = {}


def invalidate() -> None:
    """同步后主动失效缓存。"""
    _threshold_cache.clear()
    _counts_cache.clear()


# ---------------------------------------------------------------- 配置

def get_setting(key: str, default: str | None = None) -> str | None:
    with session_scope() as s:
        row = s.get(Setting, key)
        return row.value if row else default


def get_json_setting(key: str, default=None):
    raw = get_setting(key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def official_coverage() -> list:
    return get_json_setting("official_coverage", []) or []


def tier_order() -> list:
    return get_json_setting("tier_order", []) or []


# ---------------------------------------------------------------- 录取基线

def thresholds(province: str, subject: str) -> dict | None:
    """返回 {tier: {min_score, min_rank, data_source, line, school, year}}。"""
    key = (province, subject)
    now = time.time()
    hit = _threshold_cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    with session_scope() as s:
        rows = s.scalars(
            select(AdmissionBaseline).where(
                AdmissionBaseline.province == province,
                AdmissionBaseline.subject == subject,
            )
        ).all()
        if not rows:
            return None
        data = {
            r.tier: {
                "min_score": r.min_score, "min_rank": r.min_rank,
                "data_source": r.data_source, "line": r.line or None,
                "school": r.school or None, "year": r.year,
                "source_url": r.source_url or None,
            }
            for r in rows
        }
    _threshold_cache[key] = (now, data)
    return data


def baseline_rows(province: str | None = None, subject: str | None = None) -> list[dict]:
    with session_scope() as s:
        stmt = select(AdmissionBaseline)
        if province:
            stmt = stmt.where(AdmissionBaseline.province == province)
        if subject:
            stmt = stmt.where(AdmissionBaseline.subject == subject)
        rows = s.scalars(stmt.order_by(AdmissionBaseline.province, AdmissionBaseline.subject,
                                       AdmissionBaseline.min_rank)).all()
        return [{
            "id": r.id, "province": r.province, "subject": r.subject, "tier": r.tier,
            "min_score": r.min_score, "min_rank": r.min_rank,
            "data_source": r.data_source, "line": r.line, "school": r.school,
            "year": r.year, "source_url": r.source_url,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        } for r in rows]


# ---------------------------------------------------------------- 院校

def _uni_filters(stmt, province=None, level=None, tier=None, category=None,
                 q=None, nature=None):
    if province:
        stmt = stmt.where(University.province == province)
    if level:
        stmt = stmt.where(University.level == level)
    if nature:
        stmt = stmt.where(University.nature == nature)
    if tier == "985":
        stmt = stmt.where(University.is_985.is_(True))
    elif tier == "211":
        stmt = stmt.where(University.is_211.is_(True))
    elif tier == "dfc":
        stmt = stmt.where(University.is_dfc.is_(True))
    if category:
        stmt = stmt.where(University.category == category)
    if q:
        kw = f"%{q.strip()}%"
        stmt = stmt.where(or_(University.name.like(kw), University.city.like(kw)))
    return stmt


def university_counts() -> dict:
    now = time.time()
    hit = _counts_cache.get("uni")
    if hit and now - hit[0] < 60:
        return hit[1]
    with session_scope() as s:
        def count(cond=None):
            stmt = select(func.count()).select_from(University)
            if cond is not None:
                stmt = stmt.where(cond)
            return int(s.scalar(stmt) or 0)

        data = {
            "total": count(),
            "count_benke": count(University.level == "本科"),
            "count_zhuanke": count(University.level == "专科"),
            "count_985": count(University.is_985.is_(True)),
            "count_211": count(University.is_211.is_(True)),
            "count_dfc": count(University.is_dfc.is_(True)),
        }
    _counts_cache["uni"] = (now, data)
    return data


def universities(province=None, tier=None, category=None, level=None, q=None,
                 nature=None, limit: int = 500, offset: int = 0) -> dict:
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 500), 1000))
    with session_scope() as s:
        stmt = _uni_filters(select(University), province, level, tier, category, q, nature)
        total_matched = int(s.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = s.scalars(
            stmt.order_by(University.province, University.id).offset(offset).limit(limit)
        ).all()
        items = [{
            "id": r.id, "name": r.name, "province": r.province, "city": r.city,
            "level": r.level, "nature": r.nature, "supervisor": r.supervisor,
            "code": r.code, "category": r.category, "is_985": r.is_985,
            "is_211": r.is_211, "is_dfc": r.is_dfc, "website": r.website,
        } for r in rows]

    meta = university_counts()
    return {"ok": True, "count": len(items), "total_matched": total_matched,
            "offset": offset, "limit": limit, "total": meta["total"],
            "count_benke": meta["count_benke"], "count_zhuanke": meta["count_zhuanke"],
            "count_985": meta["count_985"], "count_211": meta["count_211"],
            "universities": items, "data_source": "db"}


def elite_names(tier: str) -> list[str]:
    with session_scope() as s:
        stmt = select(EliteUniversity.name)
        if tier == "985":
            stmt = stmt.where(EliteUniversity.is_985.is_(True))
        elif tier == "211":
            stmt = stmt.where(EliteUniversity.is_211.is_(True))
        else:
            return []
        return list(s.scalars(stmt.order_by(EliteUniversity.id)).all())


def province_distribution(limit: int = 10) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(University.province, func.count())
            .group_by(University.province)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()
        return [{"name": p or "未知", "value": int(c)} for p, c in rows]


def category_distribution(limit: int = 8) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(University.category, func.count())
            .where(University.category != "")
            .group_by(University.category)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()
        return [{"name": c, "value": int(n)} for c, n in rows]


# ---------------------------------------------------------------- 运营

def record_event(kind: str, province: str = "", subject: str = "", user_rank: int = 0,
                 major_name: str = "", alignment: str = "", best_tier: str = "") -> None:
    """写入匿名查询事件（失败不影响主流程）。"""
    try:
        with session_scope() as s:
            s.add(QueryEvent(kind=kind, province=province or "", subject=subject or "",
                             user_rank=int(user_rank or 0), major_name=major_name or "",
                             alignment=alignment or "", best_tier=best_tier or ""))
    except Exception:
        pass


def query_stats() -> dict:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=6)
    with session_scope() as s:
        total = int(s.scalar(select(func.count()).select_from(QueryEvent)) or 0)
        today_cnt = int(s.scalar(select(func.count()).select_from(QueryEvent)
                                 .where(QueryEvent.created_at >= today)) or 0)
        week_cnt = int(s.scalar(select(func.count()).select_from(QueryEvent)
                                .where(QueryEvent.created_at >= week)) or 0)
        verify_cnt = int(s.scalar(select(func.count()).select_from(QueryEvent)
                                  .where(QueryEvent.kind == "verify")) or 0)
        search_cnt = int(s.scalar(select(func.count()).select_from(QueryEvent)
                                  .where(QueryEvent.kind == "search")) or 0)
    return {"total": total, "today": today_cnt, "week": week_cnt,
            "verify": verify_cnt, "search": search_cnt}


def trend(days: int = 14) -> list[dict]:
    """近 N 天查询趋势（按天聚合 verify / search）。"""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    buckets = {(start + timedelta(days=i)).strftime("%m-%d"): {"verify": 0, "search": 0}
               for i in range(days)}
    with session_scope() as s:
        rows = s.execute(
            select(QueryEvent.created_at, QueryEvent.kind).where(QueryEvent.created_at >= start)
        ).all()
    for created_at, kind in rows:
        if not created_at:
            continue
        key = created_at.strftime("%m-%d")
        if key in buckets and kind in buckets[key]:
            buckets[key][kind] += 1
    return [{"date": k, **v, "total": v["verify"] + v["search"]} for k, v in buckets.items()]


def recent_events(limit: int = 50, kind: str | None = None) -> list[dict]:
    with session_scope() as s:
        stmt = select(QueryEvent).order_by(QueryEvent.id.desc()).limit(min(limit, 200))
        if kind:
            stmt = stmt.where(QueryEvent.kind == kind)
        rows = s.scalars(stmt).all()
        return [{
            "id": r.id, "kind": r.kind, "province": r.province, "subject": r.subject,
            "user_rank": r.user_rank, "major_name": r.major_name,
            "alignment": r.alignment, "best_tier": r.best_tier,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]


def recent_jobs(limit: int = 20) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(SyncJob).order_by(SyncJob.id.desc()).limit(min(limit, 100))).all()
        return [{
            "id": r.id, "kind": r.kind, "status": r.status, "total": r.total,
            "inserted": r.inserted, "updated": r.updated, "skipped": r.skipped,
            "message": r.message, "operator": r.operator,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        } for r in rows]


def content_counts() -> dict:
    with session_scope() as s:
        return {
            "majors": int(s.scalar(select(func.count()).select_from(Major)) or 0),
            "resources": int(s.scalar(select(func.count()).select_from(Resource)) or 0),
        }


def db_info() -> dict:
    path = os.environ.get("XUEFENG_DB_PATH", DEFAULT_DB_PATH)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    with session_scope() as s:
        base_rows = int(s.scalar(select(func.count()).select_from(AdmissionBaseline)) or 0)
        official_rows = int(s.scalar(
            select(func.count()).select_from(AdmissionBaseline)
            .where(AdmissionBaseline.data_source == "official")) or 0)
    return {"path": path, "size_kb": round(size / 1024, 1),
            "baseline_rows": base_rows, "official_rows": official_rows,
            "estimated_rows": base_rows - official_rows}
