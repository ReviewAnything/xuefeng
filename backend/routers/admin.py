"""管理端 API：登录鉴权、数据看板、院校/基线检索、数据同步、日志与导出。"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from db import repository as repo
from db.database import session_scope
from db.models import AdminUser
from db import seed as seed_mod
from services import admission as A
from services import admin_auth as auth
from services import data_sync as DS
from services import data_versions as DV
from services import db_config as DBC
from services import school_lines as SL

router = APIRouter(prefix="/api/admin", tags=["admin"])

TARGET_LABEL = {
    "universities": "院校总表（教育部 2868 所 + 985/211 权威清单）",
    "admission": "录取基线（31 省估算 + 11 省官方覆盖）",
    "content": "内容数据（专业图谱 / 开源资源）",
    "admin": "管理员账号与密钥",
    "ingest_baseline": "重新生成录取基线（gaokao-advisor 参数）",
    "build_universities": "重新构建全国院校总表（教育部名单）",
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
    refresh: bool = False   # pipeline 目标：拉取上游最新数据后再生成


# ---------------------------------------------------------------- 数据版本

class CloneRequest(BaseModel):
    from_year: int = Field(ge=2000, le=2100)
    to_year: int = Field(ge=2000, le=2100)
    dataset: str = "admission"
    note: str = ""


class PublishRequest(BaseModel):
    dataset: str = "admission"
    force: bool = False
    note: str = ""


class RollbackRequest(BaseModel):
    dataset: str = "admission"
    reason: str = ""


class BaselinePatch(BaseModel):
    min_score: int | None = None
    min_rank: int | None = None
    data_source: str | None = None
    line: str | None = None
    school: str | None = None
    source_url: str | None = None
    source_year: int | None = None
    carried: bool | None = None
    reason: str = ""
    publish: bool = False


class BaselineCreate(BaseModel):
    year: int
    province: str
    subject: str
    tier: str
    min_score: int
    min_rank: int
    data_source: str | None = "estimated"
    line: str | None = ""
    school: str | None = ""
    source_url: str | None = ""
    source_year: int | None = None
    carried: bool = False
    reason: str = ""


# ---------------------------------------------------------------- 鉴权

@router.post("/login")
def login(req: LoginRequest, request: Request):
    """账号密码登录：失败限流锁定（默认 5 次/5 分钟 → 锁 15 分钟），成功/失败均留审计。"""
    ip = (request.client.host if request.client else "") or ""
    ua = request.headers.get("user-agent", "")
    result = auth.login(req.username, req.password, ip=ip, user_agent=ua)
    if not result["ok"]:
        detail = result.get("detail", "用户名或密码错误")
        if result.get("reason") == "locked":
            raise HTTPException(status_code=429, detail=detail,
                                headers={"Retry-After": str(int(result.get("retry_after", 60)))})
        raise HTTPException(status_code=401, detail=detail)
    token = auth.create_token(result["user"]["username"], result["user"]["role"],
                              pwd=result.get("pwd"))
    return {"ok": True, "user": result["user"], **token}


@router.get("/login-attempts")
def login_attempts(limit: int = 50, admin: dict = Depends(auth.require_admin)):
    """最近登录审计（成功/失败/锁定），用于排查异常登录。"""
    return {"ok": True, "rows": auth.recent_attempts(max(1, min(limit, 200)))}


@router.get("/me")
def me(admin: dict = Depends(auth.require_admin)):
    return {"ok": True, "user": auth.admin_profile(admin["username"])}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request,
                    admin: dict = Depends(auth.require_admin)):
    """改密后旧令牌立即失效；响应返回新令牌，页面可直接续用。"""
    ip = (request.client.host if request.client else "") or ""
    result = auth.change_password(admin["username"], req.old_password, req.new_password, ip=ip)
    profile = auth.admin_profile(admin["username"])
    token = auth.create_token(profile["username"], profile["role"], pwd=result["pwd"])
    return {"ok": True, "message": "密码已更新，旧登录已全部失效", "user": profile, **token}


# ---------------------------------------------------------------- 数据库配置（S9-A）

class DbConfigRequest(BaseModel):
    """多数据库配置。``password`` 留空且目标库未变时表示沿用已保存口令。"""
    dialect: str = "sqlite"
    mode: str = "form"                 # form：按字段拼装 | url：直接填连接串
    host: str = ""
    port: int | None = None
    database: str = ""
    username: str = ""
    password: str = ""
    path: str = ""
    url: str = ""
    ssl: bool = False
    seed: bool = True                  # apply 时是否立即播种（默认：配置成功即落盘数据）


@router.get("/db-config")
def db_config_state(admin: dict = Depends(auth.require_admin)):
    """当前数据库配置（口令掩码）+ 各方言驱动可用性 + 上次应用结果。"""
    return DBC.state()


@router.post("/db-config/test")
def db_config_test(req: DbConfigRequest, admin: dict = Depends(auth.require_admin_ready)):
    """只试连：不改配置、不切换、不落盘。"""
    try:
        result = DBC.test_connection(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": result["ok"], **result}


@router.post("/db-config/apply")
def db_config_apply(req: DbConfigRequest, admin: dict = Depends(auth.require_admin_ready)):
    """试连 → 落盘配置 → 切换连接 → 建表迁移播种（立即初始化并落盘数据）。"""
    try:
        result = DBC.apply_config(req.model_dump(), seed=req.seed, username=admin.get("username", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not result.get("ok"):
        # 连通性/初始化失败都以 400 返回，附修复提示；服务仍停在原库上
        raise HTTPException(status_code=400, detail=result.get("error") or "配置失败",
                            headers={"X-Db-Hint": (result.get("hint") or "")[:200]})
    return {"ok": True, "message": "数据库已切换并完成初始化播种", **result}


@router.post("/db-config/reset")
def db_config_reset(admin: dict = Depends(auth.require_admin_ready)):
    """恢复默认 SQLite：清除落盘配置并重新初始化。"""
    result = DBC.reset_to_default(username=admin.get("username", ""))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "恢复默认失败")
    return {"ok": True, "message": "已恢复默认 SQLite 数据库", **result}


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


def _pending_sync(sigs: dict | None = None) -> list[str]:
    sigs = sigs or _source_signatures()
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
         "status": "ok" if db_info["active_rows"] >= 280 else "warn",
         "detail": f"{db_info['active_year']} 年生效版本 {db_info['active_rows']} 行"
                    f"（官方 {db_info['official_rows']} / 估算 {db_info['estimated_rows']}；全库 {db_info['baseline_rows']} 行）"},
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
        "active_year": repo.active_year(),
        "years": [row["year"] for row in repo.year_summary()],
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
                   year: int | None = None, admin: dict = Depends(auth.require_admin)):
    active = repo.active_year()
    rows = repo.baseline_rows(province, subject, int(year) if year else active)
    return {"ok": True, "count": len(rows), "rows": rows,
            "year": int(year) if year else active, "active_year": active}


# ---------------------------------------------------------------- 数据版本管理

@router.get("/versions")
def list_versions(dataset: str = "admission", admin: dict = Depends(auth.require_admin)):
    """数据版本总览：生效年份 + 各年份状态 + 待更新清单 + 最近变更。"""
    return DV.status(dataset)


@router.post("/versions/clone")
def clone_version(req: CloneRequest, admin: dict = Depends(auth.require_admin_ready)):
    """以某一年为蓝本创建新年度草稿（年度更新第一步）。"""
    result = DV.clone_year(req.from_year, req.to_year, dataset=req.dataset,
                           operator=admin["username"], note=req.note)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/versions/{year}/validate")
def validate_version(year: int, dataset: str = "admission",
                     admin: dict = Depends(auth.require_admin)):
    """发布前校验（覆盖、数值、单调性、来源、同比波动）。"""
    return DV.validate_year(year, dataset)


@router.post("/versions/{year}/publish")
def publish_version(year: int, req: PublishRequest | None = None,
                    admin: dict = Depends(auth.require_admin_ready)):
    req = req or PublishRequest()
    result = DV.publish_year(year, dataset=req.dataset, operator=admin["username"], force=req.force)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/versions/{year}/rollback")
def rollback_version(year: int, req: RollbackRequest | None = None,
                     admin: dict = Depends(auth.require_admin_ready)):
    req = req or RollbackRequest()
    result = DV.rollback(req.dataset, year, operator=admin["username"], reason=req.reason)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/versions/{year}/pending")
def pending_updates(year: int | None = None, dataset: str = "admission",
                    admin: dict = Depends(auth.require_admin)):
    """待更新清单（沿用往年值的行，按省份聚合）。"""
    return DV.pending_updates(year, dataset)


@router.patch("/baselines/{row_id}")
def patch_baseline(row_id: int, req: BaselinePatch,
                   admin: dict = Depends(auth.require_admin_ready)):
    """单条基线补丁（单年数据修正），逐字段留痕。"""
    result = DV.patch_baseline(row_id, req.model_dump(exclude_none=True),
                               operator=admin["username"], reason=req.reason, publish=req.publish)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/baselines")
def create_baseline(req: BaselineCreate, admin: dict = Depends(auth.require_admin_ready)):
    """补录缺失的基线行。"""
    result = DV.create_baseline(req.model_dump(), operator=admin["username"], reason=req.reason)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/changes")
def list_changes(dataset: str | None = None, year: int | None = None, limit: int = 50,
                 admin: dict = Depends(auth.require_admin)):
    return {"ok": True, "rows": DV.changes(dataset, year, limit)}


@router.post("/changes/{change_id}/undo")
def undo_change(change_id: int, admin: dict = Depends(auth.require_admin_ready)):
    result = DV.undo_change(change_id, operator=admin["username"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


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
        ("official", "11 省官方省控线", os.path.join(seed_mod.DATA_DIR, "admission_official_2024.json")),
        ("content", "专业图谱与资源", os.path.join(seed_mod.SHARED_DIR, "content.json")),
    ]
    sigs = _source_signatures()
    pending = _pending_sync(sigs)
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


@router.get("/sync/targets")
def sync_targets(admin: dict = Depends(auth.require_admin)):
    """同步目标清单（含 pipeline 类外部数据源任务）与各自最近一次执行记录。"""
    return DS.targets_catalog()


@router.post("/sync")
def sync(req: SyncRequest, admin: dict = Depends(auth.require_admin_ready)):
    """执行同步。seed 类直接播种；pipeline 类先跑 ingest/build 脚本再播种，逐个目标留痕。"""
    result = DS.run(req.targets, force=req.force, refresh=req.refresh,
                    operator=admin["username"])
    if not result.get("ok") and not result.get("results"):
        raise HTTPException(status_code=400, detail=result.get("error") or "未指定有效同步目标")
    return result


# ---------------------------------------------------------------- 院校投档线导入（D1）

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/school-lines/import")
async def import_school_lines(file: UploadFile = File(...),
                              year: int | None = Form(None),
                              province: str | None = Form(None),
                              subject: str | None = Form(None),
                              source_url: str = Form(""),
                              mode: str = Form("merge"),
                              dry_run: bool = Form(True),
                              admin: dict = Depends(auth.require_admin_ready)):
    """上传院校投档表（CSV/XLSX）：默认只返回匹配报告，`dry_run=false` 才写库。

    - 校名会与教育部 2868 所名单匹配，匹配不上的行不写库，进 `unmatched` 清单；
    - `mode=replace` 会删除同 (年份, 省, 科类) 下文件里没有的旧行，用于整省替换。
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大（上限 20MB），请拆分后上传")
    if mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode 只能是 merge 或 replace")

    defaults = {"year": year, "province": province, "subject": subject,
                "source_url": source_url,
                "data_source": "official" if source_url else ""}
    try:
        report = SL.import_table(raw, file.filename or "upload.csv", defaults,
                                 dry_run=dry_run, operator=admin["username"], mode=mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not report.get("ok"):
        raise HTTPException(status_code=400, detail=report.get("error") or "解析失败")
    return report


@router.get("/school-lines")
def admin_school_lines(province: str, subject: str, university: str | None = None,
                       year: int | None = None, limit: int = 200,
                       admin: dict = Depends(auth.require_admin)):
    return SL.lines_for(province=province, subject=subject, university=university,
                        year=year, limit=limit)


@router.get("/school-lines/coverage")
def admin_school_line_coverage(admin: dict = Depends(auth.require_admin)):
    return SL.coverage()


# ---------------------------------------------------------------- 自托管种子一键落库（S6）

class SeedImportRequest(BaseModel):
    dry_run: bool = True
    include: list[str] = Field(default_factory=lambda: ["estimated", "official"])


@router.get("/school-lines/seed-status")
def admin_school_line_seed_status(admin: dict = Depends(auth.require_admin)):
    """自托管种子可用性：仓库自带快照行数 + 官方可落库行数（只读）。"""
    return {"ok": True, **SL.seed_status()}


@router.post("/school-lines/import-seed")
def import_school_line_seed(req: SeedImportRequest | None = None,
                            admin: dict = Depends(auth.require_admin_ready)):
    """一键落库：把仓库自带的种子写进 school_lines（幂等，无需联网）。

    - ``estimated``：真实抓取快照 ``school_lines_estimated_real.json``（标 estimated_real）
    - ``official``：官方文件里的 985/211 入门投档（省考试院官方口径，标 official）

    ``dry_run=true``（默认）只返回可落库行数，不写库。
    """
    req = req or SeedImportRequest()
    include = [x for x in (req.include or []) if x in ("estimated", "official")]
    if not include:
        raise HTTPException(status_code=400, detail="include 只能是 estimated / official")
    try:
        report = SL.import_seed(commit=not req.dry_run, operator=admin["username"],
                                include=include)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"落库失败：{exc}")
    if not report.get("ok"):
        raise HTTPException(status_code=400, detail=report.get("error") or "落库失败")
    return report


# ---------------------------------------------------------------- 官方逐校投档线落库（S7-A）

class OfficialImportRequest(BaseModel):
    """官方原表落库请求：行数据 + 文件级默认值（来源链接必填）。"""
    rows: list[dict] = Field(default_factory=list)
    year: int | None = None
    province: str | None = None
    subject: str | None = None
    batch: str | None = None
    source_url: str = ""
    source_org: str = ""
    dry_run: bool = True


@router.get("/school-lines/official-status")
def admin_school_line_official_status(admin: dict = Depends(auth.require_admin)):
    """官方落地区（backend/data/official/）扫描结果：可落库行数 + 拒收明细（只读）。"""
    return {"ok": True, **SL.official_landing_rows()}


@router.post("/school-lines/import-official")
def import_school_line_official(req: OfficialImportRequest,
                                admin: dict = Depends(auth.require_admin_ready)):
    """官方原表落库（S7-A）。

    比普通校线导入更严：校名必须匹配教育部名单、分数位次不得越界，
    且**每行必须带官方来源链接**（`source_url`），否则整行拒收并给出原因——
    `official` 是最高的可信度标签，宁可少落，也不能把来路不明的行标成官方。
    """
    defaults = {k: v for k, v in {
        "year": req.year, "province": req.province, "subject": req.subject,
        "batch": req.batch, "source_url": req.source_url, "source_org": req.source_org,
    }.items() if v not in (None, "")}
    try:
        report = SL.import_official(rows=req.rows, defaults=defaults,
                                    dry_run=req.dry_run, operator=admin["username"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"官方落库失败：{exc}")
    if not report.get("ok"):
        raise HTTPException(status_code=400, detail=report.get("error") or "官方落库失败")
    return report


@router.post("/school-lines/import-official-file")
async def import_school_line_official_file(
        file: UploadFile = File(...),
        year: int | None = Form(default=None),
        province: str | None = Form(default=None),
        subject: str | None = Form(default=None),
        batch: str | None = Form(default=None),
        source_url: str = Form(default=""),
        source_org: str = Form(default=""),
        dry_run: bool = Form(default=True),
        admin: dict = Depends(auth.require_admin_ready)):
    """上传考试院原表（CSV/JSON）直接落为 official（S7-A）。来源链接必填。"""
    raw = await file.read()
    defaults = {k: v for k, v in {
        "year": year, "province": province, "subject": subject,
        "batch": batch, "source_url": source_url, "source_org": source_org,
    }.items() if v not in (None, "")}
    if not str(source_url or "").startswith(("http://", "https://")):
        raise HTTPException(status_code=400,
                            detail="官方数据必须填写来源链接 source_url（省考试院原表地址）")
    # S8-A：解析 → 强校验 → 落库 → 写溯源台账，全在一处（上传字节不落临时盘）
    try:
        report = SL.import_official_table(raw, file.filename or "", defaults,
                                          dry_run=dry_run, operator=admin["username"],
                                          register=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"官方落库失败：{exc}")
    if not report.get("ok"):
        detail = report.get("error") or "解析失败"
        if report.get("detected_headers"):
            detail += f"；识别到的表头：{report['detected_headers'][:12]}"
        raise HTTPException(status_code=400, detail=detail)
    report["parsed_rows"] = report.get("parsed", 0)
    return report


@router.get("/school-lines/official-sources")
def admin_school_line_official_sources(admin: dict = Depends(auth.require_admin)):
    """官方文件溯源台账（S8-A）：每个落过库的文件对应哪条官方链接、多少行。"""
    return {"ok": True, **SL.official_registry()}


def _parse_official_upload(raw: bytes, filename: str) -> tuple[list[dict], dict]:
    """把上传的官方原表解析成行 + 文件级默认值（复用校线导入的表头识别）。"""
    lower = (filename or "").lower()
    if lower.endswith(".json"):
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            doc = json.loads(raw.decode("utf-8-sig", errors="replace"))
        if isinstance(doc, dict):
            return list(doc.get("rows") or []), dict(doc.get("meta") or {})
        return list(doc or []), {}
    parsed = SL.parse_table(raw, filename)
    if not parsed.get("ok"):
        return [], {"error": parsed.get("error", "表头无法识别")}
    mapping = parsed["mapping"]
    rows = [{field: (r[idx] if idx < len(r) else None) for field, idx in mapping.items()}
            for r in parsed["rows"]]
    return rows, {}


# ---------------------------------------------------------------- 一分一段按省同步（S11）

class RankSyncRequest(BaseModel):
    """按省一键同步：province 必填；years 留空=该适配器登记的全部年份。"""
    province: str = Field(min_length=2, max_length=8)
    years: list[int] = Field(default_factory=list)
    dry_run: bool = False       # 只解析校验，不落盘不写库
    write_db: bool = True       # 落盘后同步写 rank_segments


@router.get("/rank-tables/provinces")
def admin_rank_provinces(admin: dict = Depends(auth.require_admin)):
    """31 省看板（含上次同步结果），管理端「按省一键同步」列表用。"""
    import rank_sync

    return {"ok": True, **rank_sync.overview()}


@router.post("/rank-tables/sync")
def admin_rank_sync(req: RankSyncRequest, admin: dict = Depends(auth.require_admin_ready)):
    """按省一键同步：抓取 → 强校验 → 落盘 → （可选）写 rank_segments。

    与 CLI ``python -m rank_sync <省>`` 走**同一条** ``parse(year)`` 路径，
    不存在「按钮能跑、脚本不能跑」的分裂。校验不过的年份整份拒收，
    返回里逐条给出失败原因；不写半份文件。
    """
    import rank_sync
    from rank_sync import common as RSC
    from services import rank_store

    rep = rank_sync.sync(req.province, years=req.years or None, dry_run=req.dry_run)
    if rep.get("error"):
        raise HTTPException(status_code=400, detail=rep["error"])
    db_rows = []
    if req.write_db and not req.dry_run:
        for r in rep["years"]:
            if not r.get("ok"):
                continue
            path = RSC.OUT_DIR / str(r["year"]) / f"{req.province}.json"
            try:
                db_rows.append(rank_store.import_file(path))
            except Exception as exc:  # noqa: BLE001 - 落库失败不影响已落盘的数据
                db_rows.append({"year": r["year"], "error": f"{type(exc).__name__}: {exc}"})
    rep["db"] = db_rows
    rep["operator"] = admin["username"]
    return rep


@router.get("/rank-tables/sync-status")
def admin_rank_sync_status(admin: dict = Depends(auth.require_admin)):
    """上次同步结果台账（逐省逐年，含失败原因）。"""
    import rank_sync

    return {"ok": True, **rank_sync.status()}


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
