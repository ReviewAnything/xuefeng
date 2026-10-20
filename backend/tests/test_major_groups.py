"""P4 院校专业组建模测试（服务层 + API）。"""
import main
from fastapi.testclient import TestClient

from services import major_groups as G

c = TestClient(main.app)


def test_subject_req_covers_known_majors():
    """专业组模型（SUBJECT_REQ）引用的每个专业都必须存在于专业图谱（content.json），
    否则 groups_for 会引用到缺失专业。
    """
    _, majors = G._load()
    missing = [name for name in G.SUBJECT_REQ if name not in majors]
    assert not missing, f"SUBJECT_REQ 含图谱中不存在的专业：{missing}"


def test_subject_req_covers_whole_graph():
    """S7-D：图谱每个专业都要有选科要求，消除「图谱 131 / 选科表 38」的缺口。

    以前只覆盖 38 个核心专业，其余专业进了图谱却推不出专业组——看着有、点下去没有。
    现在两者一一对应；图谱继续扩量时必须同步补 SUBJECT_REQ，这条用例会先拦住。
    """
    _, majors = G._load()
    assert len(majors) >= 200, f"专业图谱应已扩到 200+，当前 {len(majors)}"
    uncovered = [name for name in majors if name not in G.SUBJECT_REQ]
    assert not uncovered, f"图谱专业缺选科要求：{uncovered[:10]}（共 {len(uncovered)} 个）"
    # 选科要求只允许这四种口径（新增口径会改变专业组维度，需同步评估）
    assert set(G.SUBJECT_REQ.values()) <= set(G.REQ_ORDER)


def test_graph_entries_have_governance_fields():
    """扩量不能牺牲治理：每条都要带观点来源 / 证据等级 / 复核与失效日期。"""
    _, majors = G._load()
    bad = [name for name, m in majors.items()
           if not (m.get("view_source") and m.get("evidence_grade")
                   and m.get("expires_at") and m.get("reason") and m.get("bias"))]
    assert not bad, f"缺治理字段的专业：{bad[:10]}"


def test_category_pool_names_are_valid():
    """各院校类别专业池里的专业名必须在选科表中存在。"""
    for cat, pool in G.CATEGORY_POOL.items():
        for name in pool:
            assert name in G.SUBJECT_REQ, f"{cat} 池含未知专业 {name}"


def test_infer_category():
    assert G.infer_category("北京大学", "综合") == ("综合", "official")
    assert G.infer_category("郑州轻工业大学", None)[0] == "理工"
    assert G.infer_category("信阳师范学院", None)[0] == "师范"
    assert G.infer_category("河南中医药大学", None)[0] == "医药"
    assert G.infer_category("某某学院", None) == ("综合", "default")


def test_groups_physics():
    r = G.groups_for("北京大学", "物理类")
    assert r["ok"] and r["estimated"] is True
    assert r["university"]["name"] == "北京大学"
    assert r["university"]["category_source"] == "official"
    # S8-C：新增「地理 / 政治」两组后，综合类院校共 6 组；物理类不可报纯历史组
    assert r["total_groups"] == 6 and r["eligible_groups"] == 5
    codes = [g["group_code"] for g in r["groups"]]
    assert codes == ["01", "02", "03", "04", "05", "06"]
    reqs = {g["subject_req"]: g for g in r["groups"]}
    assert reqs["历史"]["eligible"] is False
    assert reqs["物理+化学"]["eligible"] is True
    assert all(g["major_count"] > 0 for g in r["groups"])


def test_groups_history():
    r = G.groups_for("北京大学", "历史类")
    eligible = [g["subject_req"] for g in r["groups"] if g["eligible"]]
    # S8-C：政治 / 地理属「再选科目」，历史类同样可报
    assert set(eligible) == {"不限", "历史", "政治", "地理"}
    assert all(not g["eligible"] for g in r["groups"] if g["subject_req"] == "物理+化学")
    assert all(not g["eligible"] for g in r["groups"] if g["subject_req"] == "物理")


def test_subject_req_has_politics_and_geography():
    """S8-C：政治 / 地理两类选科口径必须真实存在（S7-D 时被并进「不限」/「历史」）。"""
    assert G.SUBJECT_REQ["思想政治教育"] == "政治"
    assert G.SUBJECT_REQ["政治学与行政学"] == "政治"
    assert G.SUBJECT_REQ["警校/公安类"] == "政治"
    assert G.SUBJECT_REQ["地理信息科学"] == "地理"
    # 新增口径必须进了 REQ_ORDER 与 ELIGIBLE，否则永远不会出现在分组里
    assert {"政治", "地理"} <= set(G.REQ_ORDER)
    assert "政治" in G.ELIGIBLE["物理类"] and "政治" in G.ELIGIBLE["历史类"]
    assert "地理" in G.ELIGIBLE["物理类"] and "地理" in G.ELIGIBLE["历史类"]
    # 每个 SUBJECT_REQ 取值都要能被排序（否则该组会被静默丢掉）
    assert set(G.SUBJECT_REQ.values()) <= set(G.REQ_ORDER)


def test_groups_comprehensive_subject_has_no_restriction():
    r = G.groups_for("武汉大学", "综合/未改革")
    assert r["ok"]
    assert r["eligible_groups"] == r["total_groups"]


def test_groups_unknown_university():
    r = G.groups_for("不存在的大学")
    assert r["ok"] is False and "未收录" in r["error"]


def test_list_universities_filters():
    j = G.list_universities(only_985=True, limit=10)
    assert j["ok"] and j["total"] > 0
    assert all(it["is_985"] for it in j["items"])

    j2 = G.list_universities(province="北京", only_211=True, limit=5)
    assert all(it["province"] == "北京" for it in j2["items"])

    j3 = G.list_universities(q="师范", limit=5)
    assert all("师范" in it["name"] for it in j3["items"])


# ---------------------------------------------------------------- API

def test_api_major_groups():
    r = c.get("/api/major-groups", params={"university": "北京大学", "subject": "物理类"})
    assert r.status_code == 200
    j = r.json()
    # S8-C 后综合类院校为 6 组（物理+化学 / 物理 / 地理 / 政治 / 不限 / 历史）
    assert j["ok"] and j["total_groups"] == 6
    assert j["data_source"] == "estimated"


def test_api_major_groups_unknown_404():
    r = c.get("/api/major-groups", params={"university": "查无此校"})
    assert r.status_code == 404


def test_api_major_group_universities():
    r = c.get("/api/major-groups/universities", params={"only_985": True, "limit": 3})
    assert r.status_code == 200
    j = r.json()
    assert len(j["items"]) == 3
    assert all(it["is_985"] for it in j["items"])
