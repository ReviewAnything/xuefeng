"""志愿决策助手 · Python 后端（P2 数据层）。

FastAPI 应用，提供：
  - GET  /api/health            健康检查 + 数据源
  - GET  /api/content           单一数据源（版本/问卷）
  - GET  /api/majors            专业图谱（含视图/偏见校正）
  - GET  /api/resources         开源资源中心
  - GET  /api/admission/search  按位次筛 冲/稳/保 可达专业（数据侧）
  - POST /api/verify            观点×数据 交叉核验（P2 核心）

运行：uvicorn main:app --reload --port 8000
文档：http://localhost:8000/docs
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services import content as C
from services import admission as A
from services import verify as V

app = FastAPI(
    title="志愿决策助手 · 后端",
    description="张雪峰框架 + 开源资源 + P2 观点×数据交叉核验 API",
    version=C.APP_VERSION,
)

# 允许前端（uni-app H5 / 本地预览）跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": C.APP_VERSION,
        "data_date": C.DATA_DATE,
        "admission_data_source": A.data_source(),
        "official_provinces": A.official_coverage(),
        "majors": len(C.MAJORS),
        "resources": len(C.RESOURCES),
    }


@app.get("/api/content")
def get_content():
    return {
        "APP_VERSION": C.APP_VERSION,
        "DATA_DATE": C.DATA_DATE,
        "QUESTIONS": C.QUESTIONS,
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
    if user_rank <= 0:
        raise HTTPException(status_code=400, detail="位次必须为正整数")
    result = A.search(province, subject, user_rank, limit)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


class VerifyRequest(BaseModel):
    province: str
    subject: str
    user_rank: int = Field(gt=0, description="高考位次，必须为正整数")
    major_name: str


@app.post("/api/verify")
def verify(req: VerifyRequest):
    major = next((m for m in C.MAJORS if m["name"] == req.major_name), None)
    if not major:
        raise HTTPException(status_code=404, detail=f"未找到专业：{req.major_name}")
    result = V.verify(
        province=req.province, subject=req.subject, user_rank=req.user_rank,
        major_name=major["name"], major_cat=major["cat"], view=major["view"],
        reason=major["reason"], bias=major["bias"],
    )
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
