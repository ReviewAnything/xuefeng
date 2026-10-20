"""C2 等位分换算 + A3 院校推荐 测试（FastAPI TestClient）。运行：pytest -q。"""
import main
from fastapi.testclient import TestClient

from services import equiv_score as E
from services import recommend as R

c = TestClient(main.app)


# ---------------------------------------------------------------- C2 曲线

def test_curve_official_2024_henan():
    cur = E.curve("河南", "物理类", 2024)
    assert cur["ok"] and cur["data_source"] == "official"
    ranks = [a["rank"] for a in cur["anchors"]]
    scores = [a["score"] for a in cur["anchors"]]
    assert ranks == sorted(ranks)                 # 位次升序
    assert scores == sorted(scores, reverse=True)  # 分数降序（位次越小分越高）


def test_curve_unknown_province():
    assert not E.curve("火星", "物理类", 2024)["ok"]


def test_available_years_sorted_desc():
    years = E.available_years("河南", "物理类")
    assert len(years) >= 2
    assert [y["year"] for y in years] == sorted((y["year"] for y in years), reverse=True)


def test_score_rank_roundtrip():
    cur = E.curve("河南", "物理类", 2024)
    # 取区间内的锚点分数，反查位次后正查回分数，应近似还原
    mid = cur["anchors"][2]
    rank, ext = E.rank_of_score(cur, mid["score"])
    assert not ext
    score, ext2 = E.score_of_rank(cur, rank)
    assert not ext2
    assert abs(score - mid["score"]) <= 3


def test_score_of_rank_monotonic():
    cur = E.curve("河南", "物理类", 2024)
    pairs = [E.score_of_rank(cur, r)[0] for r in (5000, 50000, 150000, 300000, 500000)]
    assert pairs == sorted(pairs, reverse=True)


def test_extrapolated_flag_and_clamp():
    cur = E.curve("河南", "物理类", 2024)
    hi, ext = E.score_of_rank(cur, 1)
    lo, ext2 = E.score_of_rank(cur, 1_900_000)
    assert ext and ext2
    assert 0 <= lo <= hi <= 750


# ---------------------------------------------------------------- C2 API

def test_api_equiv_years():
    r = c.get("/api/equiv/years", params={"province": "河南", "subject": "物理类"})
    assert r.status_code == 200
    assert any(y["year"] == 2024 for y in r.json()["years"])


def test_api_equiv_curve():
    r = c.get("/api/equiv/curve", params={"province": "河南", "subject": "物理类", "year": 2024})
    assert r.status_code == 200
    assert r.json()["data_source"] == "official"


def test_api_equiv_convert_by_score():
    r = c.get("/api/equiv/convert", params={
        "province": "河南", "subject": "物理类", "year": 2024, "target_year": 2026, "score": 600})
    assert r.status_code == 200
    j = r.json()
    assert j["from"]["year"] == 2024 and j["to"]["year"] == 2026
    assert 0 <= j["to"]["score"] <= 750
    assert j["to"]["rank"] == j["from"]["rank"]     # rank 法：位次不变
    assert j["method"] == "rank"


def test_api_equiv_convert_by_rank():
    r = c.get("/api/equiv/convert", params={
        "province": "河南", "subject": "物理类", "year": 2024, "target_year": 2026, "rank": 40000})
    assert r.status_code == 200
    assert r.json()["from"]["rank"] == 40000


def test_api_equiv_convert_needs_input():
    r = c.get("/api/equiv/convert", params={
        "province": "河南", "subject": "物理类", "year": 2024, "target_year": 2026})
    assert r.status_code == 400


def test_api_equiv_convert_same_year():
    r = c.get("/api/equiv/convert", params={
        "province": "河南", "subject": "物理类", "year": 2024, "target_year": 2024, "rank": 100})
    assert r.status_code == 400


def test_api_equiv_convert_bad_rank_rejected():
    r = c.get("/api/equiv/convert", params={
        "province": "河南", "subject": "物理类", "year": 2024, "target_year": 2026, "rank": 0})
    assert r.status_code == 422   # Query(ge=1) 由 FastAPI 拦截


def test_api_equiv_percentile_falls_back_to_rank():
    """没有 cohort_size 时 percentile 法应回退为 rank 法并写明原因。"""
    r = c.get("/api/equiv/convert", params={
        "province": "河南", "subject": "物理类", "year": 2024, "target_year": 2026,
        "rank": 40000, "method": "percentile"})
    j = r.json()
    assert j["method"] == "rank"
    assert "percentile" in j["caveat"] and "cohort_size" in j["caveat"]


def test_percentile_method_used_when_cohort_known(monkeypatch):
    """注入真实一分一段表时，percentile 法应生效（两年规模不同 → 位次会变化）。"""
    import json
    table = {
        "河南": {"物理类": {
            "2024": {"cohort_size": 500000, "points": [[700, 100], [600, 20000], [500, 120000], [400, 300000]]},
            "2026": {"cohort_size": 600000, "points": [[700, 120], [600, 24000], [500, 144000], [400, 360000]]},
        }}
    }
    # 注意：沙箱/部分环境下 tmp_path 不可用，这里写固定临时文件（仅测试用）
    p = "/tmp/xf_score_tables_test.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(table, f)
    monkeypatch.setattr(E, "_SCORE_TABLES", p)
    E.invalidate_cache()
    try:
        out = E.convert("河南", "物理类", 2024, 2026, rank=120000, method="percentile")
        assert out["ok"] and out["method"] == "percentile"
        # 2024 年 12 万/50 万 = 24%；2026 年同百分位 = 60 万 × 24% = 14.4 万
        assert out["to"]["rank"] == 144000
        assert out["percentile"] == 0.24
    finally:
        E.invalidate_cache()


# ---------------------------------------------------------------- A3 院校推荐

def test_recommend_structure():
    r = c.get("/api/recommend/schools", params={
        "province": "河南", "subject": "物理类", "user_rank": 30000, "limit": 5})
    assert r.status_code == 200
    j = r.json()
    assert j["tiers"] and len(j["tiers"]) >= 3
    for t in j["tiers"]:
        assert t["level"] in ("冲", "稳", "保", "不可及")
        assert len(t["schools"]) <= 5
        assert t["basis"]


def test_recommend_985_pool_is_real_list():
    r = c.get("/api/recommend/schools", params={
        "province": "河南", "subject": "物理类", "user_rank": 30000, "limit": 3})
    t985 = next(t for t in r.json()["tiers"] if t["tier"] == "985")
    # 985 档应当可达（河南物理 985 入门位次 44463）
    assert t985["level"] in ("冲", "稳", "保")
    assert all("大学" in s["name"] or "学院" in s["name"] for s in t985["schools"])


def test_recommend_211_pool_excludes_985():
    j = R.recommend_schools("河南", "物理类", 30000, limit=50)
    t211 = next(t for t in j["tiers"] if t["tier"] == "211")
    assert all(not s["is_985"] for s in t211["schools"])


def test_recommend_undergrad_pool_excludes_211():
    j = R.recommend_schools("河南", "物理类", 30000, limit=50)
    benke = [t for t in j["tiers"] if t["tier"] in ("普通一本", "普通二本")]
    for t in benke:
        assert all(not s["is_211"] for s in t["schools"])


def test_recommend_low_rank_only_low_tiers_match():
    j = R.recommend_schools("河南", "物理类", 900000, limit=3)
    assert j["ok"]
    assert j["summary"]["unreachable"] >= 3   # 位次很靠后，多数层次不可及


def test_recommend_bad_rank_rejected():
    r = c.get("/api/recommend/schools", params={
        "province": "河南", "subject": "物理类", "user_rank": 0})
    assert r.status_code == 422
    r = c.get("/api/recommend/schools", params={
        "province": "河南", "subject": "物理类", "user_rank": 5_000_000})
    assert r.status_code == 422


def test_recommend_unknown_major():
    r = c.get("/api/recommend/schools", params={
        "province": "河南", "subject": "物理类", "user_rank": 30000, "major_name": "炼丹术"})
    assert r.status_code == 400


def test_recommend_with_major_adjusts_threshold():
    """同一位次下，热门专业（难度系数更高）的门槛位次应更严格。"""
    a = R.recommend_schools("河南", "物理类", 30000, limit=1)["tiers"]
    b = R.recommend_schools("河南", "物理类", 30000, major_name="计算机科学与技术", limit=1)["tiers"]
    da = {t["tier"]: t["min_rank"] for t in a}
    db = {t["tier"]: t["min_rank"] for t in b}
    assert da and db
    assert any(db[k] <= da[k] for k in db)   # 热门专业门槛位次更小（更难）
