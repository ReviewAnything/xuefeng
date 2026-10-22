"""结论页（/api/verdict）回归测试。

这个页面的验收标准不是「返回 200」，而是：
  1. 四种位次结局都要给出**不同的**判断，不能一律套模板；
  2. 结论面上不能出现「可能 / 大概 / 仅供参考 / 以…为准」——
     那等于把判断推回给用户，等于还要靠人解释；
  3. 缺数据时不许编校名（推算基线没有校名，就别写「（None）」）。
"""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

# 结论面（headline / stance / guard）上不允许出现的措辞
HEDGES = ("仅供参考", "以考试院为准", "以各省", "可能", "大概", "也许",
          "建议你", "自行判断", "不构成", "非录取结论", "估算")


def get(province, subject, rank):
    return client.get("/api/verdict", params={
        "province": province, "subject": subject, "user_rank": rank})


def decision_surface(d: dict) -> str:
    parts = [d["headline"], d["guard"]] + [s["t"] for s in d["stance"]]
    return "".join(parts)


def test_closed_985_opens_211():
    """40000 名：985 关门、211 有票 —— 结论必须点名差多少位。"""
    r = get("广东", "物理类", 40000)
    assert r.status_code == 200
    d = r.json()
    assert d["case"] == "has_211"
    assert "985 关门" in d["headline"]
    assert "10269" in d["headline"], d["headline"]
    # 省内 211 只有 2 所不是 985，这是「必须出省」这句话的全部依据
    assert any("暨南大学" in s["t"] for s in d["stance"])
    assert len(d["stance"]) >= 3
    assert len(d["bands"]) == 3


def test_open_985_does_not_hedge():
    """5000 名：985 进得去，就不该再劝人「冲一冲」。"""
    d = get("广东", "物理类", 5000).json()
    assert d["case"] == "has_985"
    assert "门没挡住你" in d["headline"]
    # 只能「否定」冲，不能建议冲
    assert "你不是在「冲」" in decision_surface(d)
    assert "冲一冲" not in decision_surface(d)
    assert d["bands"][0]["to"] < 5000


def test_narrow_211_is_not_sold_as_main_battlefield():
    """70000 名：211 只剩尾部，不能把「战场是 211」当结论。"""
    d = get("广东", "物理类", 70000).json()
    assert d["case"] == "has_211"
    assert "只剩一条缝" in d["headline"]
    keys = [s["k"] for s in d["stance"]]
    assert "别当主攻" in keys


def test_undergrad_case_by_percentile():
    """200000 名：落在本科批后段，措辞必须跟着位置变。"""
    d = get("广东", "物理类", 200000).json()
    assert d["case"] == "has_ben"
    assert "本科批" in d["headline"]
    assert "后段" in d["headline"]


def test_below_all_has_no_bands():
    """600000 名：连专科线都没到，冲稳保区间没有意义，不许给。"""
    d = get("广东", "物理类", 600000).json()
    assert d["case"] == "below_all"
    assert d["bands"] == []
    assert "路径" in d["headline"]


def test_estimated_province_has_no_none_in_copy():
    """北京走推算基线，没有校名 —— 文案里不许出现 (None)。"""
    d = get("北京", "综合/未改革", 5000).json()
    surface = decision_surface(d) + "".join(d["facts"])
    assert "None" not in surface
    assert "null" not in surface


def test_decision_surface_has_no_hedging_words():
    """结论面零对冲：四种结局逐一检查。"""
    for p, s, rk in (("广东", "物理类", 3000), ("广东", "物理类", 40000),
                     ("广东", "物理类", 70000), ("广东", "物理类", 200000),
                     ("广东", "物理类", 600000), ("河南", "物理类", 120000)):
        d = get(p, s, rk).json()
        text = decision_surface(d)
        for w in HEDGES:
            assert w not in text, f"{p}/{rk} 的结论里出现了「{w}」：{text}"


def test_percentile_never_exceeds_100():
    d = get("广东", "物理类", 200000).json()
    for f in d["facts"]:
        if "排前" in f:
            pct = float(f.split("排前")[1].replace("%", "").strip("。 "))
            assert 0 < pct <= 100


def test_two_schools_gates_are_named():
    """有校名就点名（西北农林 / 西藏大学），这是「差多少位」的可核对来源。"""
    d = get("广东", "物理类", 40000).json()
    gates = {g["tier"]: g for g in d["gates"]}
    assert gates["985"]["school"] == "西北农林科技大学"
    assert gates["211"]["school"] == "西藏大学"
    assert gates["985"]["gap"] < 0 < gates["211"]["gap"]


def test_basis_is_one_line():
    d = get("广东", "物理类", 40000).json()
    assert d["basis"].count("\n") == 0
    assert "2026" in d["basis"]


def test_invalid_rank_rejected():
    assert get("广东", "物理类", 0).status_code == 422
    assert get("广东", "物理类", 2_000_001).status_code == 422


def test_unknown_province_404():
    r = get("火星", "物理类", 1000)
    assert r.status_code == 404
    assert "暂无" in r.json()["detail"]
