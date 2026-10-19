"""后端 API + P2 逻辑测试（FastAPI TestClient，无需起服务）。运行：pytest -q。"""
import main
from fastapi.testclient import TestClient

from db import repository as repo

c = TestClient(main.app)


def test_health():
    r = c.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert j["majors"] == 38 and j["resources"] == 10


def test_majors_and_resources():
    assert c.get("/api/majors").json()["count"] == 38
    assert c.get("/api/resources", params={"cat": "tool"}).json()["count"] == 5
    assert c.get("/api/resources", params={"cat": "mind"}).json()["count"] == 5


def test_admission_search_structure():
    r = c.get("/api/admission/search", params={"province": "河南", "subject": "物理类", "user_rank": 40000})
    assert r.status_code == 200
    j = r.json()
    for key in ("reach", "match", "safe"):
        assert key in j and isinstance(j[key], list)
    # 非避坑专业应出现在可达列表
    allm = j["reach"] + j["match"] + j["safe"]
    assert len(allm) > 0
    assert all(m["view"] != "avoid" for m in allm)


def test_admission_search_unknown_province():
    r = c.get("/api/admission/search", params={"province": "火星", "subject": "物理类", "user_rank": 100})
    assert r.status_code == 404


def test_verify_aligned():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 30000, "major_name": "计算机科学与技术"})
    assert r.status_code == 200
    j = r.json()
    assert j["view"] == "recommend"
    assert j["alignment"] == "aligned"
    # 河南物理 985 官方入门位次 44463；rank 30000 真实可达 985（旧估算仅到 211）
    assert j["best_reachable"]["tier"] in ("985", "211")


def test_verify_caution_low_tier_recommend():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 210000, "major_name": "临床医学"})
    assert r.status_code == 200
    j = r.json()
    assert j["alignment"] == "caution"
    assert j["best_reachable"]["tier"] in ("普通二本", "专科")


def test_verify_conflict_avoid_low_tier():
    # 真实 31 省基线更精细：210000 已能冲上「普通一本」，故用更低位次确保只够低位次批次 -> 冲突
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 280000, "major_name": "生物工程"})
    assert r.status_code == 200
    assert r.json()["alignment"] == "conflict"


def test_verify_unknown_major():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 1000, "major_name": "不存在专业"})
    assert r.status_code == 404


def test_official_overlay_health():
    r = c.get("/api/health")
    j = r.json()
    assert j["admission_data_source"] == "official_overlay"
    assert "河南" in j["official_provinces"]


def test_official_batch_line_used():
    # 河南物理 普通一本 应命中 2024 官方省控线 511→130195
    # 用「汉语言文学」（文科保底，难度系数 identity）做精确断言
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 30000, "major_name": "汉语言文学"})
    assert r.status_code == 200
    j = r.json()
    yiben = next((t for t in j["tiers"] if t["tier"] == "普通一本"), None)
    assert yiben is not None
    assert yiben["data_source"] == "official"
    assert yiben["min_rank"] == 130195
    # 985 为学校层级，6 省已接入官方入门投档位次 → official
    top = next((t for t in j["tiers"] if t["tier"] == "985"), None)
    assert top["data_source"] == "official"
    assert top["min_rank"] == 44463   # 河南物理 985 入门：中国农业大学(中外合作)
    # 211 同理
    t211 = next((t for t in j["tiers"] if t["tier"] == "211"), None)
    assert t211["data_source"] == "official"
    assert t211["min_rank"] == 133259  # 河南物理 211 入门：西藏大学

    # 热门专业（计算机）会在官方批次线上叠加难度系数（rank_factor<1），仍标注 official 且更靠前
    r2 = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 30000, "major_name": "计算机科学与技术"})
    y2 = next((t for t in r2.json()["tiers"] if t["tier"] == "普通一本"), None)
    assert y2["data_source"] == "official"
    assert 0 < y2["min_rank"] < 130195


def test_official_unsupported_province_falls_back():
    # 北京不在官方覆盖层，全部 tier 应为 estimated（沿用估算基线）
    r = c.post("/api/verify", json={"province": "北京", "subject": "综合", "user_rank": 30000, "major_name": "计算机科学与技术"})
    assert r.status_code == 200
    j = r.json()
    assert all(t["data_source"] == "estimated" for t in j["tiers"])


def test_universities_full_list():
    # 全国普通高等学校静态总表：2868 所（本科 1308 + 专科 1560）
    r = c.get("/api/universities")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["total"] == 2868
    assert j["count_benke"] == 1308 and j["count_zhuanke"] == 1560
    # 985 计 38（教育部普通高校名单不含国防科技大学等军校）、211 计 112
    assert j["count_985"] == 38 and j["count_211"] == 112
    # 全部 211（含 985）
    r2 = c.get("/api/universities", params={"tier": "211"})
    assert r2.json()["total_matched"] == 112
    # 仅 985
    r3 = c.get("/api/universities", params={"tier": "985"})
    assert r3.json()["total_matched"] == 38
    # 校名模糊搜索
    r4 = c.get("/api/universities", params={"q": "清华"})
    assert any(u["name"] == "清华大学" for u in r4.json()["universities"])
    # 按省 + 办学层次筛选（北京共 92 所）
    r5 = c.get("/api/universities", params={"province": "北京"})
    assert r5.json()["total_matched"] == 92
    r6 = c.get("/api/universities", params={"level": "专科"})
    assert r6.json()["total_matched"] == 1560
    # 拆分校区继承 211 标记
    r7 = c.get("/api/universities", params={"q": "中国石油大学"})
    assert all(u["is_211"] for u in r7.json()["universities"]) and r7.json()["total_matched"] >= 2
    # 分页：offset=2800 应只返回剩余 68 条
    r8 = c.get("/api/universities", params={"offset": 2800, "limit": 100})
    assert r8.json()["count"] == 68 and r8.json()["total_matched"] == 2868


def test_verify_includes_reachable_schools():
    # 位次足够靠前时，可触及 985 层次并带出院校清单（39 所）
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 2000, "major_name": "计算机科学与技术"})
    assert r.status_code == 200
    j = r.json()
    assert j["reachable_tier"] == "985"
    assert j["reachable_tier_school_count"] == 39
    assert "清华大学" in j["reachable_tier_schools"]


def test_official_coverage_expanded_to_11_provinces():
    """官方省控线覆盖由 6 省扩到 11 省，且合并批次省口径一致（一本=特招线 > 二本=本科批）。"""
    rows = repo.baseline_rows()
    official = {r["province"] for r in rows if r["data_source"] == "official"}
    assert {"河南", "广东", "四川", "山东", "河北", "江苏",
            "安徽", "湖南", "湖北", "福建", "重庆"} <= official, official

    t = repo.thresholds("安徽", "物理类")
    assert t["普通一本"]["min_score"] == 514 and t["普通一本"]["min_rank"] == 107457
    assert t["普通二本"]["min_score"] == 465 and t["普通二本"]["min_rank"] == 176157
    assert t["专科"]["min_score"] == 200 and t["专科"]["min_rank"] == 313412
    assert t["普通一本"]["data_source"] == "official"

    for prov, sub in [("湖南", "历史类"), ("湖北", "物理类"), ("福建", "历史类"),
                      ("重庆", "物理类"), ("江苏", "物理类"), ("广东", "历史类"),
                      ("河北", "物理类")]:
        t = repo.thresholds(prov, sub)
        assert t["普通一本"]["min_rank"] < t["普通二本"]["min_rank"] < t["专科"]["min_rank"], (prov, sub)
        assert t["普通一本"]["min_score"] > t["普通二本"]["min_score"] > t["专科"]["min_score"], (prov, sub)


# ---------------------------------------------------------------- P1→P2 批量核验

def test_verify_batch_returns_summary_and_risk_first_order():
    majors = c.get("/api/majors").json()["majors"]
    names = [m["name"] for m in majors[:8]]
    r = c.post("/api/verify/batch", json={
        "province": "河南", "subject": "物理类", "user_rank": 40000, "major_names": names})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] == 8
    assert j["summary"]["total"] == 8
    assert j["summary"]["aligned"] + j["summary"]["caution"] + j["summary"]["conflict"] == 8
    order = {"conflict": 0, "caution": 1, "aligned": 2}
    seq = [order[x["alignment"]] for x in j["results"]]
    assert seq == sorted(seq), "结果应按 冲突 → 需谨慎 → 一致 排序"
    assert all(x["province"] == "河南" for x in j["results"])


def test_verify_batch_rejects_empty_and_too_many():
    base = {"province": "河南", "subject": "物理类", "user_rank": 40000}
    assert c.post("/api/verify/batch", json={**base, "major_names": []}).status_code == 400
    too_many = c.post("/api/verify/batch", json={**base, "major_names": ["法学"] * 21})
    assert too_many.status_code == 400
    assert "20" in too_many.json()["detail"]


def test_verify_batch_unknown_major_is_reported_not_fatal():
    r = c.post("/api/verify/batch", json={
        "province": "河南", "subject": "物理类", "user_rank": 40000,
        "major_names": ["法学", "不存在的专业"]})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    assert r.json()["unknown"] == ["不存在的专业"]


# ---------------------------------------------------------------- 输入校验

def test_user_rank_upper_bound_is_rejected():
    too_big = 10 ** 8
    r1 = c.post("/api/verify", json={"province": "河南", "subject": "物理类",
                                     "user_rank": too_big, "major_name": "法学"})
    assert r1.status_code == 422
    r2 = c.get("/api/admission/search",
               params={"province": "河南", "subject": "物理类", "user_rank": too_big})
    assert r2.status_code == 400
    assert "合理范围" in r2.json()["detail"]


def test_classify_rejects_invalid_rank():
    from services import admission as A
    assert A.classify(0, 10000) == "不可及"
    assert A.classify(A.MAX_USER_RANK + 1, 10000) == "不可及"
    assert A.validate_user_rank(0)
    assert A.validate_user_rank(A.MAX_USER_RANK + 1)
    assert A.validate_user_rank(40000) == ""


# ---------------------------------------------------------------- CORS 白名单

def test_cors_default_is_localhost_only():
    assert "*" not in main.CORS_ORIGINS
    assert "http://localhost:5173" in main.CORS_ORIGINS
    assert c.get("/api/health").json()["cors_origins"] == main.CORS_ORIGINS


def test_cors_origins_from_env(monkeypatch):
    import importlib
    monkeypatch.setenv("XUEFENG_CORS_ORIGINS", "https://a.example.com, https://b.example.com")
    try:
        m = importlib.reload(main)
        assert m.CORS_ORIGINS == ["https://a.example.com", "https://b.example.com"]
    finally:
        monkeypatch.delenv("XUEFENG_CORS_ORIGINS", raising=False)
        importlib.reload(main)


# ---------------------------------------------------------------- 内容可溯

def test_content_provenance_is_exposed():
    j = c.get("/api/content").json()
    cs = j["content_source"]
    assert cs["compiled_year"] >= 2026
    assert cs["view_basis"] and cs["data_basis"] and cs["caveat"]
    majors = c.get("/api/majors").json()["majors"]
    assert len(majors) == 38
    assert all(m.get("source_year") and m.get("source_note") for m in majors)
