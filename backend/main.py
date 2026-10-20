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
  - GET  /api/recommend/schools 院校推荐：按位次给出 冲/稳/保 院校清单（A3）
  - GET  /api/major-groups/universities 院校选择器（按省/层次/985/211/关键字）
  - GET  /api/major-groups     新高考「院校专业组」推导（专业选科要求 × 院校类别专业池）
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
from services import verify as V
from services import equiv_score as E
from services import recommend as R
from services import major_groups as MG
from db import init_db
from db import repository as repo
from routers import admin as admin_api

APP_VERSION = C.APP_VERSION

app = FastAPI(
    title="志愿决策助手 · 后端",
    description="张雪峰框架 + 开源资源 + P2 观点×数据交叉核验 API + 管理端",
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

# 启动即初始化数据库：建表 + 幂等播种（源文件未变则跳过）
DB_BOOT = {}
try:
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
        db_counts = repo.university_counts()
        db_ok = True
    except Exception:
        db_counts, db_ok = {}, False
    return {
        "status": "ok",
        "version": APP_VERSION,
        "data_date": C.DATA_DATE,
        "admission_data_source": A.data_source(),
        "official_provinces": A.official_coverage(),
        "majors": len(C.MAJORS),
        "resources": len(C.RESOURCES),
        "cors_origins": CORS_ORIGINS,
        "database": {
            "enabled": db_ok,
            "universities": db_counts.get("total", 0),
            "count_985": db_counts.get("count_985", 0),
            "count_211": db_counts.get("count_211", 0),
        },
        "admin_console": None if DISABLE_ADMIN else "/admin",
    }


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
                          alignment=r["alignment"], best_tier=best.get("tier", ""))
    s = result["summary"]
    repo.record_event("verify_batch", province=req.province, subject=req.subject,
                      user_rank=req.user_rank, major_name=f"{len(result['results'])}个专业",
                      alignment=f"冲突{s['conflict']}/谨慎{s['caution']}/一致{s['aligned']}")
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
