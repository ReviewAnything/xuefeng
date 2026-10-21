"""后端 API + P2 逻辑测试（FastAPI TestClient，无需起服务）。运行：pytest -q。"""
import main
from fastapi.testclient import TestClient

from sqlalchemy import delete

from db import repository as repo
from db import session_scope
from db.models import SchoolLine
from services import school_lines as SL

c = TestClient(main.app)

# S2 起 alignment 可计算（supported/refuted/unverified）；S0 红线：永不出现旧的 conflict/aligned。
ALLOWED_ALIGNMENT = ("unverified", "supported", "refuted")


def test_health():
    r = c.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    # S4 扩到 131，S7-D 再扩到 212（unverified 红线不变）
    assert j["majors"] >= 200 and j["resources"] == 10


def test_majors_and_resources():
    assert c.get("/api/majors").json()["count"] >= 200   # S4 38 → 131，S7-D → 212
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


def test_verify_reachability_high():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 30000, "major_name": "计算机科学与技术"})
    assert r.status_code == 200
    j = r.json()
    assert j["view"] == "recommend"
    # S0：证据一致性因缺校线趋势恒为 unverified，不再给 aligned/conflict
    assert j["alignment"] in ALLOWED_ALIGNMENT
    assert j["reachability"] == "high"   # 位次可达 985/211 层次
    assert j["best_reachable"]["tier"] in ("985", "211")
    # 治理字段已随 content.json 升级补齐
    assert j["evidence_grade"] == "A"
    assert j["view_source"]


def test_verify_reachability_low_tier():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 210000, "major_name": "临床医学"})
    assert r.status_code == 200
    j = r.json()
    assert j["alignment"] in ALLOWED_ALIGNMENT
    assert j["reachability"] == "low"   # 位次只够二本/专科
    assert j["best_reachable"]["tier"] in ("普通二本", "专科")


def test_verify_avoid_low_tier_is_reachability_not_conflict():
    # 避坑专业 + 低位次：S0 之前误报「冲突」，现在是诚实的 reachability=low，alignment 恒 unverified
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 280000, "major_name": "生物工程"})
    assert r.status_code == 200
    j = r.json()
    assert j["alignment"] in ALLOWED_ALIGNMENT
    assert j["reachability"] == "low"
    assert j["reachability_label"] == "仅够低层次"


def test_verify_unknown_major():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 1000, "major_name": "不存在专业"})
    assert r.status_code == 404


def test_official_overlay_health():
    r = c.get("/api/health")
    j = r.json()
    assert j["admission_data_source"] == "official_overlay"
    assert "河南" in j["official_provinces"]


def test_school_line_authority_split_in_health():
    """S5-A：健康上报院校投档线的权威分级（official / estimated_real / 覆盖省数）。"""
    r = c.get("/api/health")
    j = r.json()
    sl = j["school_lines"]
    assert sl["official"] == 0
    assert sl["estimated_real"] == 14020
    assert sl["provinces"] == 30
    assert sl["grade"] == "estimated_real"
    assert sl["has_official"] is False


def test_verify_raw_records_carry_data_source_and_summary():
    """S5-A：核验结果逐条校线带 data_source/source_label，并带整体权威摘要。"""
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 40000,
                                    "major_name": "计算机科学与技术"})
    assert r.status_code == 200
    j = r.json()
    assert j["school_line_grade"] == "estimated_real"
    assert j["school_line_summary"]["estimated_real"] > 0
    assert j["school_line_summary"]["official"] == 0
    recs = j["raw_records"]
    assert recs, "应带出真实校线逐条记录"
    for rec in recs:
        assert rec["data_source"] == "estimated_real"
        assert rec["source_label"] == "真实抓取"
    # 数据来源侧摘要也应反映官方/抓取拆分
    data_src = next((s for s in j["sources"] if s["kind"] == "data"), None)
    assert data_src and "data_source_summary" in data_src


def test_official_batch_line_used():
    # 河南物理 普通一本 应命中官方省控线（阳光高考 2026 转录，分数权威）；
    # 省控线主表不含位次，min_rank 保留 estimated 基线值（>0，不置 0）
    # 用「汉语言文学」（难度系数 identity）做精确断言
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 30000, "major_name": "汉语言文学"})
    assert r.status_code == 200
    j = r.json()
    yiben = next((t for t in j["tiers"] if t["tier"] == "普通一本"), None)
    assert yiben is not None
    assert yiben["data_source"] == "official"
    assert yiben["min_rank"] > 0
    # 985 为学校层级，6 省已接入官方入门投档位次（旧文件，带真实位次）→ official
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
    assert 0 < y2["min_rank"] < yiben["min_rank"]


def test_official_unsupported_province_falls_back():
    # 北京属合并批次省（科目=综合），已在 31 省官方省控线覆盖内 → 普通一本/二本为 official；
    # 但 985/211 校线仅 6 省接入官方（北京不在其中）→ 校线回落 estimated。
    # 验证「省控线官方 + 校线回落」的分层兜底逻辑。
    r = c.post("/api/verify", json={"province": "北京", "subject": "综合", "user_rank": 30000, "major_name": "计算机科学与技术"})
    assert r.status_code == 200
    j = r.json()
    yiben = next((t for t in j["tiers"] if t["tier"] == "普通一本"), None)
    top = next((t for t in j["tiers"] if t["tier"] == "985"), None)
    assert yiben["data_source"] == "official"      # 省控线已官方覆盖
    assert top["data_source"] == "estimated"       # 校线未官方覆盖，回落估算


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


def test_official_coverage_expanded_to_31_provinces():
    """官方省控线覆盖由 11 省扩到 31 省（阳光高考逐年主表全量转录）。

    省控线主表不含位次，官方行的 min_rank 保留 estimated 基线值（来自一分一段表），
    避免把生效年份的官方行 min_rank 置 0 拉垮冲稳保实时排名。
    """
    rows = repo.baseline_rows()
    official = {r["province"] for r in rows if r["data_source"] == "official"}
    # 旧 11 省仍是官方子集；整体应达 31 省
    assert {"河南", "广东", "四川", "山东", "河北", "江苏",
            "安徽", "湖南", "湖北", "福建", "重庆"} <= official, official
    assert len(official) == 31, f"官方省控线应覆盖 31 省，实际 {len(official)}"

    t = repo.thresholds("安徽", "物理类")
    # 分数为 2026 阳光高考官方值；位次为 estimated 基线（>0，非 0）
    assert t["普通一本"]["min_score"] == 514 and t["普通一本"]["min_rank"] > 0
    assert t["普通二本"]["min_score"] == 451 and t["普通二本"]["min_rank"] > 0
    assert t["专科"]["min_score"] == 200 and t["专科"]["min_rank"] > 0
    assert t["普通一本"]["data_source"] == "official"

    for prov, sub in [("湖南", "历史类"), ("湖北", "物理类"), ("福建", "历史类"),
                      ("重庆", "物理类"), ("江苏", "物理类"), ("广东", "历史类"),
                      ("河北", "物理类"), ("上海", "综合"), ("西藏", "物理类")]:
        t = repo.thresholds(prov, sub)
        assert t["普通一本"]["min_rank"] < t["普通二本"]["min_rank"] < t["专科"]["min_rank"], (prov, sub)
        assert t["普通一本"]["min_score"] > t["普通二本"]["min_score"] > t["专科"]["min_score"], (prov, sub)


# ---------------------------------------------------------------- P1→P2 批量核验

def test_school_line_official_coverage_structure():
    """S9-D：官方行覆盖率结构正确，且不能把「少数 official 行」误读成「数据都官方」。

    默认种子库不含 official 校线（官方行须经管理端「一键落库」写入），故此处显式落一批
    官方种子行以验证覆盖率口径，结束后清理，避免污染其它用例。

    断言：
      - 返回含 groups / schools 两大块；
      - groups 含 official/total/ratio/ratio_pct 四键；
      - 22 行 985/211 官方入门投档远小于全量专业组，故 official < total 且 ratio_pct < 100；
      - schools 含 official/total/ratio 三键。
    """
    # 默认确实无 official 行（设计：官方行须经「一键落库」写入）
    assert SL.official_coverage()["groups"]["official"] == 0
    try:
        SL.import_seed(include=["official"])
        cov = SL.official_coverage()
        assert set(cov) == {"groups", "schools"}, cov
        g = cov["groups"]
        assert set(g) == {"official", "total", "ratio", "ratio_pct"}, g
        sch = cov["schools"]
        assert set(sch) == {"official", "total", "ratio"}, sch
        assert g["official"] > 0, "落库后应有 official 专业组被统计"
        assert g["total"] > g["official"], "全量专业组应显著多于官方覆盖专业组"
        assert 0 < g["ratio_pct"] < 100, f"覆盖率应为 0~100 之间，实际 {g['ratio_pct']}"
        assert round(g["ratio"] * 100, 1) == g["ratio_pct"]
        assert sch["official"] > 0 and sch["total"] >= sch["official"]
    finally:
        with session_scope() as s:
            s.execute(delete(SchoolLine).where(
                SchoolLine.data_source == "official", SchoolLine.year == 2024))
        SL.invalidate_cache()


def test_health_exposes_school_line_official_coverage():
    """S9-D：/api/health 的 school_lines.official_coverage 透传结构。"""
    r = c.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    cov = j["school_lines"]["official_coverage"]
    assert set(cov) == {"groups", "schools"}, cov
    assert set(cov["groups"]) == {"official", "total", "ratio", "ratio_pct"}


def test_verify_school_line_summary_has_official_coverage():
    """S9-D：/api/verify 的 school_line_summary 携带 official_coverage。"""
    majors = c.get("/api/majors").json()["majors"]
    name = majors[0]["name"]
    r = c.post("/api/verify", json={
        "province": "河南", "subject": "物理类", "user_rank": 40000,
        "major_name": name})
    assert r.status_code == 200, r.text
    j = r.json()
    cov = j["school_line_summary"]["official_coverage"]
    assert set(cov) == {"groups", "schools"}, cov
    assert cov["groups"]["total"] > 0


def test_verify_batch_summary_and_reachability_order():
    majors = c.get("/api/majors").json()["majors"]
    names = [m["name"] for m in majors[:8]]
    r = c.post("/api/verify/batch", json={
        "province": "河南", "subject": "物理类", "user_rank": 40000, "major_names": names})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] == 8
    s = j["summary"]
    assert s["total"] == 8
    assert s["out_of_reach"] + s["low"] + s["mid"] + s["high"] == 8
    # 风险优先：不可及 → 低位次 → 一本 → 高层次
    order = {"out_of_reach": 0, "low": 1, "mid": 2, "high": 3}
    seq = [order[x["reachability"]] for x in j["results"]]
    assert seq == sorted(seq), "结果应按可及性风险优先排序"
    assert all(x["province"] == "河南" for x in j["results"])
    # S0 验收：批量结果不得出现 conflict/aligned（alignment 只取 allowed 集合）
    assert all(x["alignment"] in ALLOWED_ALIGNMENT for x in j["results"])


def test_no_alignment_conflict_or_aligned_ever():
    """S0 红线：任何专业 / 任何位次都不得返回旧的 conflict / aligned；
    S2 起 alignment 只取 {unverified, supported, refuted}（数据侧仅核验可及性）。"""
    majors = c.get("/api/majors").json()["majors"]
    for m in majors:
        for rank in (2000, 40000, 120000, 280000):
            r = c.post("/api/verify", json={
                "province": "河南", "subject": "物理类", "user_rank": rank,
                "major_name": m["name"]})
            if r.status_code != 200:
                continue
            j = r.json()
            assert j["alignment"] in ALLOWED_ALIGNMENT
            assert j["alignment"] not in ("conflict", "aligned")
            assert j["reachability"] in ("out_of_reach", "low", "mid", "high")


def test_alignment_unverified_when_no_school_line():
    """S0 真正成立的场景：某 (省/科类) 未导入真实校线时，alignment 恒为 unverified
    （单侧降级，不出现 supported/refuted）。西藏-历史类是当前唯一未导入校线的基线组合。"""
    r = c.post("/api/verify", json={
        "province": "西藏", "subject": "历史类", "user_rank": 40000, "major_name": "法学"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["alignment"] == "unverified"
    assert j["real_data"] is None or j["real_data"].get("has_data") is False


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
    assert cs.get("framework") == "就业确定性优先（普通家庭 + 就业导向的务实决策方法）"
    majors = c.get("/api/majors").json()["majors"]
    assert len(majors) >= 200   # S4 图谱扩量 38 → 131，S7-D → 212
    assert all(m.get("source_year") and m.get("source_note") for m in majors)


def test_content_governance_fields_present():
    """S1：每条观点都补齐治理字段（view_source / evidence_grade / reviewed_at / expires_at）。"""
    majors = c.get("/api/majors").json()["majors"]
    assert len(majors) >= 200   # S4 图谱扩量 38 → 131，S7-D → 212
    for m in majors:
        assert m.get("evidence_grade") in ("A", "B", "C")
        assert m.get("view_source")
        assert m.get("reviewed_at")
        assert m.get("expires_at")


def test_health_reports_pending_view_reviews():
    """S1 验收：/api/health 能报「待复核观点 N 条」。"""
    j = c.get("/api/health").json()
    assert "pending_views" in j
    assert isinstance(j["pending_views"], int)
    assert j["pending_views"] >= 0


def test_validate_content_ok():
    from services import content as C
    res = C.validate_content()
    assert res["ok"] is True, res
    assert res["stats"]["majors"] >= 200   # S4 图谱扩量 38 → 131，S7-D → 212
    assert "pending" in res["stats"]
