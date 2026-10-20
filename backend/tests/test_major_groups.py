"""P4 院校专业组建模测试（服务层 + API）。"""
import main
from fastapi.testclient import TestClient

from services import major_groups as G

c = TestClient(main.app)


def test_subject_req_covers_all_majors():
    """每个专业都必须有选科要求，否则专业组推导会漏专业。"""
    _, majors = G._load()
    assert set(majors.keys()) == set(G.SUBJECT_REQ.keys())


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
    assert r["total_groups"] == 4 and r["eligible_groups"] == 3
    codes = [g["group_code"] for g in r["groups"]]
    assert codes == ["01", "02", "03", "04"]
    reqs = {g["subject_req"]: g for g in r["groups"]}
    # 物理类不可报纯历史组
    assert reqs["历史"]["eligible"] is False
    assert reqs["物理+化学"]["eligible"] is True
    assert all(g["major_count"] > 0 for g in r["groups"])


def test_groups_history():
    r = G.groups_for("北京大学", "历史类")
    eligible = [g["subject_req"] for g in r["groups"] if g["eligible"]]
    assert set(eligible) == {"不限", "历史"}
    # 历史类不能报物理+化学组
    assert all(not g["eligible"] for g in r["groups"] if g["subject_req"] == "物理+化学")


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
    assert j["ok"] and j["total_groups"] == 4
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
