"""管理端 API：登录鉴权、数据看板、院校/基线检索、数据同步、日志与导出。"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from db import repository as repo
from db.database import session_scope
from db.models import AdminUser, SyncJob
from db import seed as seed_mod
from services import admission as A
from services import admin_auth as auth

router = APIRouter(prefix="/api/admin", tags=["admin"])

TARGET_LABEL = {
    "universities": "院校总表（教育部 2868 所 + 985/211 权威清单）",
    "admission": "录取基线（31 省估算 + 6 省官方覆盖）",
    "content": "内容数据（专业图谱 / 开源资源）",
    "admin": "管理员账号与密钥",
}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class SyncRequest(BaseModel):
    targets: list[str] = Field(default_factory=lambda: ["universities", "admission", "content"])
    force: bool = False


# ---------------------------------------------------------------- 鉴权

@router.post("/login")
def login(req: LoginRequest):
    user = auth.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = auth.create_token(user["username"], user["role"])
    return {"ok": True, "user": user, **token}


@router.get("/me")
def me(admin: dict = Depends(auth.require_admin)):
    return {"ok": True, "user": auth.admin_profile(admin["username"])}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, admin: dict = Depends(auth.require_admin)):
    auth.change_password(admin["username"], req.old_password, req.new_password)
    return {"ok": True, "message": "密码已更新"}


# ---------------------------------------------------------------- 看板

def _source_signatures() -> dict:
    return {
        "universities": seed_mod._signature(
            os.path.join(seed_mod.DATA_DIR, "universities_national.json"),
            os.path.join(seed_mod.DATA_DIR, "universities.json")),
        "admission": seed_mod._signature(
            os.path.join(seed_mod.DATA_DIR, "admission_real_baseline.json"),
            os.path.join(seed_mod.DATA_DIR, "admission_official_2024.json")),
        "content": seed_mod._signature(os.path.join(seed_mod.SHARED_DIR, "content.json")),
    }


def _pending_sync() -> list[str]:
    sigs = _source_signatures()
    pending = []
    with session_scope() as s:
        for target, sig in sigs.items():
            from db.models import Setting
            row = s.get(Setting, f"seed_sig:{target}")
            if row is None or row.value != sig:
                pending.append(target)
    return pending


@router.get("/overview")
def overview(admin: dict = Depends(auth.require_admin)):
    counts = repo.university_counts()
    content = repo.content_counts()
    queries = repo.query_stats()
    db_info = repo.db_info()
    coverage = repo.official_coverage()
    pending = _pending_sync()
    jobs = repo.recent_jobs(6)

    profile = auth.admin_profile(admin["username"])
    checks = [
        {"key": "db", "label": "数据库连接", "status": "ok",
         "detail": f"{db_info['path']} · {db_info['size_kb']} KB"},
        {"key": "universities", "label": "院校总表", "status": "ok" if counts["total"] == 2868 else "warn",
         "detail": f"{counts['total']} 所（本科 {counts['count_benke']} / 专科 {counts['count_zhuanke']}）"},
        {"key": "elite", "label": "985/211 权威清单",
         "status": "ok" if counts["count_985"] >= 38 and counts["count_211"] == 112 else "warn",
         "detail": f"985 {counts['count_985']} 所 · 211 {counts['count_211']} 所"},
        {"key": "baselines", "label": "录取基线",
         "status": "ok" if db_info["baseline_rows"] >= 280 else "warn",
         "detail": f"{db_info['baseline_rows']} 行（官方 {db_info['official_rows']} / 估算 {db_info['estimated_rows']}）"},
        {"key": "official", "label": "官方数据覆盖",
         "status": "ok" if coverage else "warn",
         "detail": f"{len(coverage)} 省：{'、'.join(coverage) if coverage else '未接入'}"},
        {"key": "content", "label": "内容数据",
         "status": "ok" if content["majors"] == 38 else "warn",
         "detail": f"专业 {content['majors']} · 资源 {content['resources']}"},
        {"key": "sync", "label": "数据同步状态",
         "status": "warn" if pending else "ok",
         "detail": ("待同步：" + "、".join(TARGET_LABEL.get(p, p) for p in pending)) if pending else "所有数据源均为最新"},
        {"key": "password", "label": "管理员密码",
         "status": "warn" if profile.get("must_change_password") else "ok",
         "detail": "仍为初始密码，建议立即修改" if profile.get("must_change_password") else "已修改"},
    ]

    level_dist = [
        {"name": "本科", "value": counts["count_benke"]},
        {"name": "专科", "value": counts["count_zhuanke"]},
    ]
    non_985_211 = max(0, counts["count_211"] - counts["count_985"])
    tier_dist = [
        {"name": "985", "value": counts["count_985"]},
        {"name": "211（非985）", "value": non_985_211},
        {"name": "普通本科", "value": max(0, counts["count_benke"] - counts["count_211"])},
        {"name": "高职专科", "value": counts["count_zhuanke"]},
    ]

    return {
        "ok": True,
        "admin": {"username": admin["username"], "must_change_password": profile.get("must_change_password")},
        "kpis": {
            "universities": counts["total"],
            "benke": counts["count_benke"],
            "zhuanke": counts["count_zhuanke"],
            "elite_985": counts["count_985"],
            "elite_211": counts["count_211"],
            "majors": content["majors"],
            "resources": content["resources"],
            "queries_today": queries["today"],
            "queries_week": queries["week"],
            "queries_total": queries["total"],
            "official_provinces": len(coverage),
            "official_rows": db_info["official_rows"],
            "baseline_rows": db_info["baseline_rows"],
            "db_size_kb": db_info["size_kb"],
            "pending_sync": len(pending),
        },
        "trend": repo.trend(14),
        "province_dist": repo.province_distribution(10),
        "level_dist": level_dist,
        "tier_dist": tier_dist,
        "checks": checks,
        "jobs": jobs,
        "coverage": coverage,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/meta")
def meta(admin: dict = Depends(auth.require_admin)):
    with session_scope() as s:
        provinces = [r[0] for r in s.execute(
            select(repo.AdmissionBaseline.province).distinct()
            .order_by(repo.AdmissionBaseline.province)).all()]
        nature = [r[0] for r in s.execute(
            select(repo.University.nature).distinct()
            .where(repo.University.nature != "").order_by(repo.University.nature)).all()]
    return {
        "ok": True,
        "provinces": provinces,
        "subjects": ["物理类", "历史类", "综合"],
        "levels": ["本科", "专科"],
        "natures": nature,
        "tiers": repo.tier_order(),
        "official_coverage": repo.official_coverage(),
        "content": repo.get_json_setting("content_meta", {}),
        "admission": repo.get_json_setting("admission_meta", {}),
        "targets": TARGET_LABEL,
    }


# ---------------------------------------------------------------- 数据浏览

@router.get("/universities")
def list_universities(q: str | None = None, province: str | None = None,
                      level: str | None = None, tier: str | None = None,
                      category: str | None = None, nature: str | None = None,
                      page: int = 1, page_size: int = 20,
                      admin: dict = Depends(auth.require_admin)):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    result = repo.universities(province=province, tier=tier, category=category,
                               level=level, q=q, nature=nature,
                               limit=page_size, offset=(page - 1) * page_size)
    return {**result, "page": page, "page_size": page_size,
            "pages": max(1, (result["total_matched"] + page_size - 1) // page_size)}


@router.get("/baselines")
def list_baselines(province: str | None = None, subject: str | None = None,
                   admin: dict = Depends(auth.require_admin)):
    rows = repo.baseline_rows(province, subject)
    return {"ok": True, "count": len(rows), "rows": rows}


@router.get("/events")
def list_events(limit: int = 50, kind: str | None = None,
                admin: dict = Depends(auth.require_admin)):
    return {"ok": True, "rows": repo.recent_events(limit, kind), "stats": repo.query_stats()}


@router.get("/jobs")
def list_jobs(limit: int = 20, admin: dict = Depends(auth.require_admin)):
    return {"ok": True, "rows": repo.recent_jobs(limit)}


# ---------------------------------------------------------------- 数据源与同步

@router.get("/sources")
def sources(admin: dict = Depends(auth.require_admin)):
    """数据源文件状态：大小、更新时间、行数、是否待同步。"""
    specs = [
        ("universities", "全国普通高校总表", os.path.join(seed_mod.DATA_DIR, "universities_national.json")),
        ("elite", "985/211 权威清单", os.path.join(seed_mod.DATA_DIR, "universities.json")),
        ("baseline", "31 省录取基线", os.path.join(seed_mod.DATA_DIR, "admission_real_baseline.json")),
        ("official", "6 省官方省控线", os.path.join(seed_mod.DATA_DIR, "admission_official_2024.json")),
        ("content", "专业图谱与资源", os.path.join(seed_mod.SHARED_DIR, "content.json")),
    ]
    sigs = _source_signatures()
    pending = _pending_sync()
    out = []
    for key, label, path in specs:
        if not os.path.exists(path):
            out.append({"key": key, "label": label, "path": path, "exists": False,
                        "size_kb": 0, "modified_at": None, "rows": 0})
            continue
        rows = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if key == "content":
                rows = len(doc.get("MAJORS", [])) + len(doc.get("RESOURCES", []))
            elif key == "baseline":
                rows = sum(len(t) for subj in doc.get("tier_baseline", {}).values() for t in subj.values())
            elif key in ("universities", "elite"):
                rows = len(doc.get("universities", []))
            else:
                rows = len(doc.get("batch_lines", {}))
        except Exception:
            rows = 0
        out.append({
            "key": key, "label": label, "path": path, "exists": True,
            "size_kb": round(os.path.getsize(path) / 1024, 1),
            "modified_at": datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat(),
            "rows": rows,
        })
    return {"ok": True, "files": out, "pending": pending, "targets": TARGET_LABEL,
            "signatures": sigs}


@router.post("/sync")
def sync(req: SyncRequest, admin: dict = Depends(auth.require_admin)):
    targets = [t for t in req.targets if t in seed_mod.TARGETS]
    if not targets:
        raise HTTPException(status_code=400, detail="未指定有效同步目标")
    with session_scope() as s:
        job = SyncJob(kind=",".join(targets), status="running", operator=admin["username"])
        s.add(job)
        s.flush()
        job_id = job.id
    try:
        stats = seed_mod.sync_all(targets, force=req.force)
        A.invalidate_cache()
        totals = {"total": 0, "inserted": 0, "updated": 0, "skipped": 0}
        for value in stats.values():
            if isinstance(value, dict):
                for k in totals:
                    totals[k] += int(value.get(k, 0) or 0)
        message = "；".join(f"{TARGET_LABEL.get(k, k)}: 新增 {v.get('inserted', 0)} / 更新 {v.get('updated', 0)}"
                            for k, v in stats.items() if isinstance(v, dict)) or "无变化"
        with session_scope() as s:
            j = s.get(SyncJob, job_id)
            j.status = "success"
            j.total, j.inserted, j.updated, j.skipped = (totals["total"], totals["inserted"],
                                                         totals["updated"], totals["skipped"])
            j.message = message
            j.finished_at = datetime.now(timezone.utc)
        return {"ok": True, "job_id": job_id, "targets": targets, "stats": stats,
                "summary": totals, "message": message}
    except Exception as exc:
        with session_scope() as s:
            j = s.get(SyncJob, job_id)
            j.status = "failed"
            j.message = f"{type(exc).__name__}: {exc}"
            j.finished_at = datetime.now(timezone.utc)
        raise HTTPException(status_code=500, detail=f"同步失败：{exc}")


# ---------------------------------------------------------------- 导出

@router.get("/export/universities.csv")
def export_universities(token: str | None = Query(default=None),
                        admin: dict = Depends(auth.require_admin_flexible)):
    result = repo.universities(limit=1000, offset=0)
    total = result["total_matched"]
    rows = []
    offset = 0
    while offset < total:
        batch = repo.universities(limit=1000, offset=offset)
        rows.extend(batch["universities"])
        offset += 1000
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["校名", "省份", "城市", "办学层次", "办学性质", "主管部门", "门类", "985", "211", "双一流", "标识码"])
    for u in rows:
        writer.writerow([u["name"], u["province"], u["city"], u["level"], u["nature"],
                         u["supervisor"], u["category"], "是" if u["is_985"] else "",
                         "是" if u["is_211"] else "", "是" if u["is_dfc"] else "", u["code"]])
    data = "\ufeff" + buf.getvalue()
    filename = f"universities-{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(iter([data.encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/baselines.csv")
def export_baselines(token: str | None = Query(default=None),
                     admin: dict = Depends(auth.require_admin_flexible)):
    rows = repo.baseline_rows()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["省份", "科类", "批次", "最低分", "最低位次", "数据来源", "官方线", "入门院校", "年份", "来源"])
    for r in rows:
        writer.writerow([r["province"], r["subject"], r["tier"], r["min_score"], r["min_rank"],
                         r["data_source"], r["line"], r["school"], r["year"], r["source_url"]])
    data = "\ufeff" + buf.getvalue()
    filename = f"admission-baselines-{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(iter([data.encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/accounts")
def accounts(admin: dict = Depends(auth.require_admin)):
    with session_scope() as s:
        rows = s.scalars(select(AdminUser)).all()
        return {"ok": True, "rows": [{
            "id": u.id, "username": u.username, "role": u.role,
            "must_change_password": u.must_change_password,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        } for u in rows]}
