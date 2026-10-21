"""志愿决策助手 · Python 后端。

FastAPI 应用，提供：
  - GET  /api/health            健康检查 + 数据源
  - GET  /api/content           单一数据源（版本/问卷）
  - GET  /api/majors            专业图谱（含视图/偏见校正）
  - GET  /api/resources         开源资源中心
  - GET  /api/admission/search  按位次筛 冲/稳/保 可达专业（数据侧）
  - GET  /api/universities      全国普通高等学校静态总表（2868 所：本科 1308 + 专科 1560）
  - POST /api/verify            观点×数据 交叉核验（P2 核心）
  - POST /api/verify/batch      批量交叉核验（P1→P2 打通：画布推荐方向一次算完）
  - GET  /api/equiv/years       等位分换算：某省/科类可用的年份与数据源
  - GET  /api/equiv/curve       等位分换算：某年「位次→分数」锚点曲线
  - GET  /api/equiv/convert     等位分换算：分数/位次 跨年换算（rank / percentile 两法）
  - GET  /api/verdict           结论：位次 → 一句判断 + 放弃/主攻/保底三个动作（决策入口）
  - GET  /api/recommend/schools 院校推荐：按位次给出 冲/稳/保 院校清单（A3）
  - GET  /api/major-groups/universities 院校选择器（按省/层次/985/211/关键字）
  - GET  /api/major-groups     新高考「院校专业组」推导（专业选科要求 × 院校类别专业池）
  - GET  /api/school-lines     院校投档线（逐校真实数据，D1 导入后可用）
  - GET  /api/school-lines/coverage 院校投档线覆盖概况
  - /api/admin/*                管理端：登录、看板、数据浏览、同步、导出
  - /admin                      管理端控制台（Vue3 + Element Plus）

数据默认落库到 SQLite（backend/data/xuefeng.db），由 db/seed.py 从 JSON 幂等播种。

运行：uvicorn main:app --reload --port 8000
文档：http://localhost:8000/docs
"""
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from services import content as C
from services import admission as A
from services import control_lines as CL
from services import rank_tables as RT
from services import verify as V
from services import equiv_score as E
from services import recommend as R
from services import major_groups as MG
from services import school_lines as SL
from services import verdict as VD
from services import observability as OBS
from services import db_config as DBC
from db import init_db
from db import repository as repo
from routers import admin as admin_api

APP_VERSION = C.APP_VERSION

app = FastAPI(
    title="志愿决策助手 · 后端",
    description="就业确定性优先 + 开源资源 + P2 观点×数据交叉核验 API + 管理端",
    version=APP_VERSION,
)

# 允许前端跨域调用。默认放行本地开发端口，生产环境用
# XUEFENG_CORS_ORIGINS="https://a.example.com,https://b.example.com" 显式白名单，
# 避免 CORS 全开带来的数据被任意站点读取风险。
def _cors_origins() -> list[str]:
    raw = os.environ.get("XUEFENG_CORS_ORIGINS", "").strip()
    if raw == "*":
        return ["*"]
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:5173", "http://127.0.0.1:5173",   # uni-app H5 dev
        "http://localhost:8000", "http://127.0.0.1:8000",   # 本机后端 / 管理端
        "http://localhost:8080", "http://127.0.0.1:8080",
    ]


CORS_ORIGINS = _cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 访问日志：每请求一个 request id + 一行 JSON（慢请求标 warn）
OBS.install(app)

# 启动先装载管理端落盘的数据库配置（backend/data/db_config.json），
# 再初始化数据库：建表 + 幂等播种（源文件未变则跳过）。
# 环境变量 XUEFENG_DATABASE_URL / XUEFENG_DB_PATH 优先级更高，部署态不会被页面配置覆盖。
DB_BOOT = {}
try:
    DBC.bootstrap()
    DB_BOOT = init_db()
except Exception as exc:  # 落库失败时仍可依赖 JSON 兜底对外服务
    DB_BOOT = {"error": f"{type(exc).__name__}: {exc}"}

# 公开 demo 部署（C1）时可用 XUEFENG_DISABLE_ADMIN=1 关掉管理端：
# 只保留只读的公开 API，避免把管理端控制台/默认口令暴露在公网上。
DISABLE_ADMIN = os.environ.get("XUEFENG_DISABLE_ADMIN", "").strip().lower() in ("1", "true", "yes")
if not DISABLE_ADMIN:
    app.include_router(admin_api.router)

_ADMIN_DIR = os.path.join(os.path.dirname(__file__), "admin")
if os.path.isdir(_ADMIN_DIR) and not DISABLE_ADMIN:
    app.mount("/admin", StaticFiles(directory=_ADMIN_DIR, html=True), name="admin")


@app.get("/", include_in_schema=False)
def root():
    if DISABLE_ADMIN:
        return {"app": "志愿决策助手 · 公开 API", "docs": "/docs", "health": "/api/health"}
    return RedirectResponse("/admin")


@app.get("/api/health")
def health():
    try:
        from db.database import active_url_source, database_url
        DBC_ACTIVE_URL = database_url()          # 运行期可切换，故每次现取
        DBC_SOURCE = active_url_source()
    except Exception:
        DBC_ACTIVE_URL, DBC_SOURCE = "", "unknown"
    try:
        db_counts = repo.university_counts()
        db_info = repo.db_info()
        db_ok = True
    except Exception:
        db_counts, db_info, db_ok = {}, {"active_year": None}, False
    try:
        school_lines = SL.coverage()
    except Exception:
        school_lines = {"total": 0, "years": []}
    try:
        sl_sources = SL.source_counts()
    except Exception:
        sl_sources = {"total": 0, "by_source": {}, "official": 0,
                      "estimated_real": 0, "provinces": [], "province_count": 0,
                      "has_official": False, "grade": "estimated_real"}
    # S7-A：官方逐校投档线落地区是否就绪、有多少行待落库
    try:
        landing = SL.official_landing_rows()
    except Exception:
        landing = {"dir_exists": False, "accepted_count": 0, "rejected_count": 0, "files": []}
    # S7-B：自托管种子的完整性与体积
    try:
        seed_state = SL.verify_seed()
    except Exception:
        seed_state = {"exists": False, "ok": False, "rows": 0, "sha256": "", "size_bytes": 0}
    # S8-A：官方文件溯源台账（几个文件 / 多少行 / 覆盖哪些省）
    try:
        official_sources = SL.official_registry()
    except Exception:
        official_sources = {"count": 0, "rows": 0, "provinces": [], "files": []}
    # S8-B：证据门槛校准台账（各 (省/科类) 落哪一档）
    try:
        from services.verify import gate_profile
        gate = gate_profile()
    except Exception:
        gate = {"combos": 0, "bands": {"full": 0, "thin": 0, "none": 0}, "thresholds": {}}
    return {
        "status": "ok",
        "version": APP_VERSION,
        "data_date": C.DATA_DATE,
        "admission_data_source": A.data_source(),
        "official_provinces": A.official_coverage(),
        "active_year": db_info.get("active_year"),
        "majors": len(C.MAJORS),
        "resources": len(C.RESOURCES),
        "cors_origins": CORS_ORIGINS,
        "database": {
            "enabled": db_ok,
            "dialect": DBC._dialect_of_url(DBC_ACTIVE_URL),
            "url": DBC._mask_url(DBC_ACTIVE_URL),
            "config_source": DBC_SOURCE,
            "size_kb": db_info.get("size_kb", 0),
            "universities": db_counts.get("total", 0),
            "count_985": db_counts.get("count_985", 0),
            "count_211": db_counts.get("count_211", 0),
        },
        "school_lines": {"total": school_lines.get("total", 0),
                         "years": [y["year"] for y in school_lines.get("years", [])],
                         "official": sl_sources.get("official", 0),
                         "estimated_real": sl_sources.get("estimated_real", 0),
                         "provinces": sl_sources.get("province_count", 0),
                         "grade": sl_sources.get("grade", "estimated_real"),
                         "has_official": sl_sources.get("has_official", False),
                         "official_coverage": sl_sources.get("official_coverage", {}),
                         "official_landing": {
                             "dir_ready": landing.get("dir_exists", False),
                             "pending_rows": landing.get("accepted_count", 0),
                             "rejected_rows": landing.get("rejected_count", 0),
                             "files": [f["file"] for f in landing.get("files", [])]},
                         "seed": {"available": seed_state.get("exists", False),
                                  "rows": seed_state.get("rows", 0),
                                  "sha256_ok": bool(seed_state.get("ok")),
                                  "compressed": str(seed_state.get("path", "")).endswith(".gz"),
                                  "size_kb": round(seed_state.get("size_bytes", 0) / 1024, 1)},
                         # S8-A：官方文件溯源台账
                         "official_sources": {"files": official_sources.get("count", 0),
                                              "rows": official_sources.get("rows", 0),
                                              "provinces": official_sources.get("provinces", [])},
                         # S8-B：证据门槛校准（各组合落在 full / thin / none 哪档）
                         "evidence_gate": {"combos": gate.get("combos", 0),
                                           "bands": gate.get("bands", {}),
                                           "thresholds": gate.get("thresholds", {})}},
        "pending_views": C.pending_reviews(),
        "observability": OBS.snapshot(recent=5),
        "admin_console": None if DISABLE_ADMIN else "/admin",
    }


@app.get("/api/admission/control-line-years")
def control_line_years():
    """近五年官方省控线：可用年份、覆盖省份、来源链接（年度罗盘入口）。"""
    return CL.available_years()


@app.get("/api/admission/control-lines")
def control_lines(year: int, province: str = None):
    """近五年官方省控线按年查询（年度罗盘）。

    year：必填，2022–2026 之一；province：可选，限定单省。
    数据来自阳光高考逐年官方主表，含 source_url 可追溯，不含一分一段位次。
    """
    return CL.get_control_lines(year, province)


@app.get("/api/rank-tables")
def rank_tables_overview():
    """一分一段表覆盖概览：年份 × 省份 × 科类（官方成绩分段统计，按年落盘）。"""
    return {"years": RT.years()}


@app.get("/api/rank-tables/provinces")
def rank_tables_provinces():
    """31 省看板：适配器是否就绪 / 已落盘年份 / 上次同步结果（管理端一键同步的数据源）。"""
    import rank_sync

    return rank_sync.overview()


@app.get("/api/rank-tables/{year}/{province}")
def rank_table_doc(year: int, province: str):
    """单年单省完整一分一段表（含 source_url 溯源与顶部分数备注）。"""
    d = RT.doc(year, province)
    if not d:
        raise HTTPException(404, f"无 {province} {year} 年一分一段数据")
    return d


@app.get("/api/rank-tables/lookup")
def rank_table_lookup(year: int, province: str, subject: str, score: int):
    """分数 -> 位次（cum_ben=本科档累计、cum_zhuan=专科档累计，两档口径不同）。"""
    r = RT.lookup(year, province, subject, score)
    if not r:
        raise HTTPException(404, "无匹配数据（年份/省份/科类/分数超出覆盖）")
    return r


@app.get("/api/content")
def get_content():
    return {
        "APP_VERSION": C.APP_VERSION,
        "DATA_DATE": C.DATA_DATE,
        "QUESTIONS": C.QUESTIONS,
        "content_source": C.CONTENT_SOURCE,
        "admission_data_source": A.data_source(),
    }


@app.get("/api/majors")
def get_majors(cat: str = "all"):
    majors = C.MAJORS if cat == "all" else [m for m in C.MAJORS if m["cat"] == cat]
    return {"count": len(majors), "majors": majors}


@app.get("/api/resources")
def get_resources(cat: str = "all"):
    res = C.RESOURCES if cat == "all" else [r for r in C.RESOURCES if r["cat"] == cat]
    return {"count": len(res), "resources": res}


@app.get("/api/admission/search")
def admission_search(province: str, subject: str, user_rank: int, limit: int = 20):
    err = A.validate_user_rank(user_rank)
    if err:
        raise HTTPException(status_code=400, detail=err)
    result = A.search(province, subject, user_rank, limit)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    repo.record_event("search", province=province, subject=subject, user_rank=user_rank)
    return result


@app.get("/api/universities")
def universities(province: str = None, tier: str = None, category: str = None,
                 level: str = None, q: str = None, nature: str = None,
                 limit: int = 500, offset: int = 0):
    """全国普通高等学校静态总表（教育部官方名单，2868 所：本科 1308 + 专科 1560）。

    可按 省(province)/层次(tier: 985|211|dfc)/门类(category)/办学层次(level: 本科|专科)/
    办学性质(nature)/校名(q) 筛选；分页 limit/offset，total_matched 为过滤后总数。
    """
    result = A.universities(province=province, tier=tier, category=category,
                            level=level, q=q, nature=nature, limit=limit, offset=offset)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


class VerifyRequest(BaseModel):
    province: str
    subject: str
    user_rank: int = Field(gt=0, le=A.MAX_USER_RANK, description="高考位次，必须为正整数")
    major_name: str


class VerifyBatchRequest(BaseModel):
    province: str
    subject: str
    user_rank: int = Field(gt=0, le=A.MAX_USER_RANK, description="高考位次，必须为正整数")
    major_names: list[str] = Field(default_factory=list, description=f"待核验专业名，最多 {V.MAX_BATCH} 个")


@app.post("/api/verify")
def verify(req: VerifyRequest):
    major = next((m for m in C.MAJORS if m["name"] == req.major_name), None)
    if not major:
        raise HTTPException(status_code=404, detail=f"未找到专业：{req.major_name}")
    result = V.verify_major_entry(req.province, req.subject, req.user_rank, major)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    best = result.get("best_reachable") or {}
    repo.record_event("verify", province=req.province, subject=req.subject,
                      user_rank=req.user_rank, major_name=req.major_name,
                      alignment=result.get("alignment", ""), best_tier=best.get("tier", ""))
    return result


@app.post("/api/verify/batch")
def verify_batch(req: VerifyBatchRequest):
    """P1→P2 打通：一次核验多个专业（诊断画布的推荐方向 / 数据侧冲稳保列表）。

    结果按「冲突 → 需谨慎 → 一致」排序，让用户先看风险项。
    """
    names = [n.strip() for n in req.major_names if isinstance(n, str) and n.strip()]
    if not names:
        raise HTTPException(status_code=400, detail="major_names 不能为空")
    if len(names) > V.MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"单次最多核验 {V.MAX_BATCH} 个专业")

    index = {m["name"]: m for m in C.MAJORS}
    picked = [n for n in names if n in index]
    unknown = [n for n in names if n not in index]
    if not picked:
        raise HTTPException(status_code=404, detail=f"未找到专业：{unknown[0]}")

    result = V.verify_many(req.province, req.subject, req.user_rank,
                           [index[n] for n in picked])
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    if unknown:
        result["unknown"] = unknown

    for r in result["results"]:
        best = r.get("best_reachable") or {}
        repo.record_event("verify", province=req.province, subject=req.subject,
                          user_rank=req.user_rank, major_name=r["major"],
                          alignment=r["reachability"], best_tier=best.get("tier", ""))
    s = result["summary"]
    repo.record_event("verify_batch", province=req.province, subject=req.subject,
                      user_rank=req.user_rank, major_name=f"{len(result['results'])}个专业",
                      alignment=f"不可及{s['out_of_reach']}/低{s['low']}/一本{s['mid']}/高{s['high']}")
    return result


# ---------------------------------------------------------------- 等位分换算（C2）

@app.get("/api/equiv/years")
def equiv_years(province: str, subject: str):
    """某省/科类可用年份：官方省控线年 + 估算基线年 + 可选的一分一段表年。"""
    return {"ok": True, "province": province, "subject": subject,
            "years": E.available_years(province, subject)}


@app.get("/api/equiv/curve")
def equiv_curve(province: str, subject: str, year: int = Query(..., ge=2000, le=2100)):
    """某年「位次 → 分数」锚点曲线（一分一段的稀疏近似）。"""
    r = E.curve(province, subject, year)
    if not r["ok"]:
        raise HTTPException(status_code=404, detail=r["error"])
    return r


@app.get("/api/equiv/convert")
def equiv_convert(province: str, subject: str,
                  year: int = Query(..., ge=2000, le=2100),
                  target_year: int = Query(..., ge=2000, le=2100),
                  score: float = Query(None, ge=0, le=750),
                  rank: int = Query(None, ge=1, le=A.MAX_USER_RANK),
                  method: str = Query("rank", pattern="^(rank|percentile)$")):
    """跨年等位分换算：分数/位次 → 目标年的等效分数与位次。

    score 与 rank 至少给一个（同时给出以 rank 为准）。
    method=rank（同位次等效分，默认）或 percentile（按考生规模归一，需 cohort_size）。
    """
    r = E.convert(province, subject, year, target_year, score=score, rank=rank, method=method)
    if not r["ok"]:
        code = 404 if "暂无" in r["error"] else 400
        raise HTTPException(status_code=code, detail=r["error"])
    repo.record_event("equiv", province=province, subject=subject,
                      user_rank=r["from"]["rank"], alignment=f"{year}->{target_year}")
    return r


# ---------------------------------------------------------------- 结论（决策入口）

@app.get("/api/verdict")
def verdict(province: str, subject: str,
            user_rank: int = Query(..., gt=0, le=A.MAX_USER_RANK)):
    """位次 → 一句判断 + 放弃/主攻/保底三个动作。

    与 `/api/recommend/schools` 的区别：那个给「池子」，这个给「结论」。
    结论页不铺口径，来源与沿用年份收在 basis 一行。
    """
    r = VD.build(province=province, subject=subject, user_rank=user_rank)
    if not r["ok"]:
        code = 404 if "暂无" in r["error"] else 400
        raise HTTPException(status_code=code, detail=r["error"])
    repo.record_event("verdict", province=province, subject=subject, user_rank=user_rank,
                      best_tier=r.get("case") or "")
    return r


# ---------------------------------------------------------------- 院校推荐（A3）

@app.get("/api/recommend/schools")
def recommend_schools(province: str, subject: str,
                      user_rank: int = Query(..., gt=0, le=A.MAX_USER_RANK),
                      major_name: str = None,
                      limit: int = Query(12, ge=1, le=R.MAX_LIMIT),
                      nature: str = None, category: str = None, q: str = None,
                      prefer_local: bool = True):
    """按位次给出 冲/稳/保 三档院校清单（教育部 2868 所名单 + 各省批次门槛位次）。"""
    r = R.recommend_schools(province=province, subject=subject, user_rank=user_rank,
                            major_name=major_name, limit=limit, nature=nature,
                            category=category, q=q, prefer_local=prefer_local)
    if not r["ok"]:
        code = 404 if "暂无" in r["error"] else 400
        raise HTTPException(status_code=code, detail=r["error"])
    top = next((t for t in r["tiers"] if t["level"] != "不可及"), None)
    repo.record_event("recommend", province=province, subject=subject, user_rank=user_rank,
                      major_name=major_name or "", best_tier=top["tier"] if top else "")
    return r


# ---------------------------------------------------------------- 院校专业组（P4）

@app.get("/api/major-groups/universities")
def major_group_universities(province: str = None, level: str = None,
                             only_985: bool = False, only_211: bool = False,
                             q: str = None,
                             limit: int = Query(30, ge=1, le=100)):
    """院校选择器：按省 / 本科专科 / 985·211 / 关键字筛选（含类别与类别来源）。"""
    return MG.list_universities(province=province, level=level, only_985=only_985,
                                only_211=only_211, q=q, limit=limit)


@app.get("/api/major-groups")
def major_groups(university: str, subject: str = "物理类"):
    """推导某院校的「院校专业组」结构：按专业选科要求聚组，返回是否可报。

    数据为规则推导（estimated），非官方公布的专业组划分。
    """
    r = MG.groups_for(university=university, subject=subject)
    if not r["ok"]:
        raise HTTPException(status_code=404, detail=r["error"])
    repo.record_event("major_groups", province=r["university"].get("province") or "",
                      subject=r["student_subject"], major_name=university,
                      best_tier=f"{r['eligible_groups']}/{r['total_groups']}")
    return r


# ---------------------------------------------------------------- 院校投档线（D1）

@app.get("/api/school-lines")
def school_lines(province: str, subject: str, university: str = None,
                 year: int = None, limit: int = Query(100, ge=1, le=1000)):
    """院校投档线查询：某省/科类下逐校（可到专业组）的最低分与最低位次。

    数据来自管理端导入的各省投档表；未导入时返回空列表（前端应回退到层次估算）。
    """
    return SL.lines_for(province=province, subject=subject, university=university,
                        year=year, limit=limit)


@app.get("/api/school-lines/coverage")
def school_lines_coverage():
    """院校投档线覆盖概况：按年份统计行数、覆盖省份与院校数。"""
    return SL.coverage()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
