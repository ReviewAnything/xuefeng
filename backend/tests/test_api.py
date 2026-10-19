"""后端 API + P2 逻辑测试（FastAPI TestClient，无需起服务）。运行：pytest -q。"""
import main
from fastapi.testclient import TestClient

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
    assert j["best_reachable"]["tier"] == "211"


def test_verify_caution_low_tier_recommend():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 210000, "major_name": "临床医学"})
    assert r.status_code == 200
    j = r.json()
    assert j["alignment"] == "caution"
    assert j["best_reachable"]["tier"] in ("普通二本", "专科")


def test_verify_conflict_avoid_low_tier():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 210000, "major_name": "生物工程"})
    assert r.status_code == 200
    assert r.json()["alignment"] == "conflict"


def test_verify_unknown_major():
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 1000, "major_name": "不存在专业"})
    assert r.status_code == 404
