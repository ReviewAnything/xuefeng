"""S10-B 志愿个数上限：服务 + 端点测试。运行：pytest -q。"""
import main
from fastapi.testclient import TestClient

from services import volunteer_limits as VL

c = TestClient(main.app)


def test_service_get_known_province():
    g = VL.get("广东")
    assert g and g["mode"] == "院校专业组"
    assert g["undergrad"] == 45 and g["junior"] == 45


def test_service_split_preset_for_112():
    r = VL.recommended_split("辽宁")
    assert r["undergrad"] == 112
    assert r["mode"] == "专业+院校"
    # 112 档用公开建议分布
    assert r["split"] == {"reach": 40, "match": 33, "safe": 39}


def test_service_split_generic_for_48():
    r = VL.recommended_split("河南")
    assert r["undergrad"] == 48
    assert r["mode"] == "院校专业组"
    s = r["split"]
    # 48 档无预设，按 15/50/35 估算，且三档之和恰为上限
    assert s["reach"] + s["match"] + s["safe"] == 48


def test_service_unknown_province_returns_none():
    assert VL.get("火星") is None
    assert VL.recommended_split("火星") is None


def test_endpoint_returns_limit():
    r = c.get("/api/admission/volunteer-limit", params={"province": "辽宁"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["province"] == "辽宁"
    assert j["undergrad"] == 112
    assert j["split"]["reach"] == 40


def test_endpoint_unknown_province_404():
    r = c.get("/api/admission/volunteer-limit", params={"province": "火星"})
    assert r.status_code == 404
