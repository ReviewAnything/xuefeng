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
    # 985/211 为学校层级，官方无对应省控线口径，仍估算
    top = next((t for t in j["tiers"] if t["tier"] == "985"), None)
    assert top["data_source"] == "estimated"

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
    # 完整静态清单：112 所，其中 39 所 985
    r = c.get("/api/universities")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["total"] == 112
    assert j["count_985"] == 39
    assert j["count"] == 112
    # 全部 211（含 985）
    r2 = c.get("/api/universities", params={"tier": "211"})
    assert r2.json()["count"] == 112
    # 仅 985
    r3 = c.get("/api/universities", params={"tier": "985"})
    assert r3.json()["count"] == 39
    # 校名模糊搜索
    r4 = c.get("/api/universities", params={"q": "清华"})
    assert r4.json()["count"] == 1 and r4.json()["universities"][0]["name"] == "清华大学"
    # 按省筛选
    r5 = c.get("/api/universities", params={"province": "北京"})
    assert r5.json()["count"] == 23  # 北京 985(8) + 211 非985(15) = 23


def test_verify_includes_reachable_schools():
    # 位次足够靠前时，可触及 985 层次并带出院校清单（39 所）
    r = c.post("/api/verify", json={"province": "河南", "subject": "物理类", "user_rank": 2000, "major_name": "计算机科学与技术"})
    assert r.status_code == 200
    j = r.json()
    assert j["reachable_tier"] == "985"
    assert j["reachable_tier_school_count"] == 39
    assert "清华大学" in j["reachable_tier_schools"]
