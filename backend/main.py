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
  - /api/admin/*                管理端：登录、看板、数据浏览、同步、导出
  - /admin                      管理端控制台（Vue3 + Element Plus）

数据默认落库到 SQLite（backend/data/xuefeng.db），由 db/seed.py 从 JSON 幂等播种。

运行：uvicorn main:app --reload --port 8000
文档：http://localhost:8000/docs
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from services import content as C
from services import admission as A
from services import verify as V
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

app.include_router(admin_api.router)

_ADMIN_DIR = os.path.join(os.path.dirname(__file__), "admin")
if os.path.isdir(_ADMIN_DIR):
    app.mount("/admin", StaticFiles(directory=_ADMIN_DIR, html=True), name="admin")


@app.get("/", include_in_schema=False)
def root():
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
        "admin_console": "/admin",
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
