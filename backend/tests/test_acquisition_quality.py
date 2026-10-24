"""P0/P1/P2 数据治理测试：采集台账、位次交叉校验、跨年突变、同键官方优先、原表留档。"""
import json
import os
import tempfile

import main
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from db.database import session_scope
from db.models import DataChange, SchoolLine
from services import acquisition as ACQ
from services import data_quality as DQ
from services import school_lines as SL
from tests.helpers import ready_headers

c = TestClient(main.app)

YEAR = 2098
TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bk_tmp")


def _tmpdir(tag: str) -> str:
    os.makedirs(TEST_DIR, exist_ok=True)
    return tempfile.mkdtemp(prefix=f"{tag}-", dir=TEST_DIR)


def _mkrow(university: str, group_code: str, rank: int, source: str,
           year: int = YEAR, province: str = "河南", subject: str = "物理类",
           score: int = 600) -> SchoolLine:
    return SchoolLine(
        year=year, province=province, subject=subject, batch="普通类本科批",
        university=university, university_input=university, group_code=group_code,
        min_score=score, min_rank=rank, data_source=source, match_method="exact",
        source_url="https://example.gov.cn/t" if source == "official" else "",
        note="", operator="test", updated_at=None)


def _cleanup_lines():
    # 本文件所有落库行 operator 均为 "test"：按 operator 精确清理，
    # 避免遗留 2024 年 official 行污染 test_school_line_official 的全局 official==0 断言
    with session_scope() as s:
        s.execute(delete(SchoolLine).where(SchoolLine.year == YEAR))
        s.execute(delete(SchoolLine).where(SchoolLine.operator == "test"))
        s.execute(delete(DataChange).where(DataChange.dataset == "school_lines"))
    SL.invalidate_cache()


# ---------------------------------------------------------------- 同键官方优先（map_for）

def test_map_for_prefers_official_over_estimated():
    """同年同校 official 与 estimated_real 并存时，推荐取数应选官方口径。"""
    _cleanup_lines()
    try:
        with session_scope() as s:
            s.add(_mkrow("清华大学", "01", 30000, "estimated_real"))
            s.add(_mkrow("清华大学", "官方投档", 50000, "official"))
        got = SL.map_for("河南", "物理类", ["清华大学"], year=YEAR)
        assert "清华大学" in got
        rec = got["清华大学"]
        assert rec["data_source"] == "official", "官方行必须优先于估算行"
        assert rec["group_code"] == "官方投档"
        # 年份优先于官方性：更新的年份仍胜出（口径新比标签贵）
        with session_scope() as s:
            s.add(_mkrow("北京大学", "官方投档", 100, "official", year=YEAR - 1))
            s.add(_mkrow("北京大学", "01", 200, "estimated_real", year=YEAR))
        got2 = SL.map_for("河南", "物理类", ["北京大学"])
        assert got2["北京大学"]["year"] == YEAR
        assert got2["北京大学"]["data_source"] == "estimated_real"
    finally:
        _cleanup_lines()


# ---------------------------------------------------------------- 位次交叉校验

def _rank_table_available() -> bool:
    return DQ._expected_rank(2024, "广东", "物理类", 665) is not None


@pytest.mark.skipif(not _rank_table_available(), reason="需要广东 2024 一分一段表落盘数据")
def test_cross_check_flags_deviation_and_passes_consistent_row():
    """分数经一分一段表反查位次，偏差超阈值告警；一致的行不告警。"""
    expected = DQ._expected_rank(2024, "广东", "物理类", 665)
    assert expected and expected > 0
    bad = {"year": 2024, "province": "广东", "subject": "物理类",
           "university": "测试大学", "min_score": 665, "min_rank": 200000, "note": ""}
    w = DQ.cross_check(bad)
    assert w is not None and w["expected_rank"] == expected and w["deviation"] > 1
    good = {"year": 2024, "province": "广东", "subject": "物理类",
            "university": "测试大学", "min_score": 665, "min_rank": expected, "note": ""}
    assert DQ.cross_check(good) is None, "与一分一段表一致的行不应告警"

    res = DQ.annotate_cross_check([bad])
    assert res["checked"] == 1 and len(res["warnings"]) == 1
    assert "需人工复核" in bad["note"], "告警应写进行备注（疑点留在数据里）"


def test_import_official_attaches_cross_check_report():
    """官方落库报告应携带 cross_check 摘要（dry-run 也有，便于预览）。"""
    rows = [{"university": "中山大学", "province": "广东", "subject": "物理类",
             "year": 2024, "min_score": 624, "min_rank": 12345,
             "source_url": "https://eea.gd.gov.cn/test", "group_code": "201"}]
    rep = SL.import_official(rows, dry_run=True, operator="test")
    assert rep["ok"] and rep["accepted"] == 1
    assert "cross_check" in rep
    _cleanup_lines()


# ---------------------------------------------------------------- 跨年突变

def test_year_over_year_anomalies_detects_jump():
    _cleanup_lines()
    try:
        with session_scope() as s:
            s.add(_mkrow("突变大学", "01", 1000, "official", year=YEAR))
            s.add(_mkrow("突变大学", "01", 5000, "official", year=YEAR + 1))
            s.add(_mkrow("平稳大学", "01", 1000, "official", year=YEAR))
            s.add(_mkrow("平稳大学", "01", 1100, "official", year=YEAR + 1))
        anomalies = DQ.year_over_year_anomalies()
        hit = [a for a in anomalies if a["university"] == "突变大学"]
        calm = [a for a in anomalies if a["university"] == "平稳大学"]
        assert hit and hit[0]["change_pct"] == 400.0
        assert not calm, "10% 的正常波动不应误报"
    finally:
        _cleanup_lines()


# ---------------------------------------------------------------- 采集台账

def test_acquisition_upsert_and_matrix(monkeypatch):
    ledger = os.path.join(_tmpdir("acq"), "acquisition_ledger.json")
    monkeypatch.setattr(ACQ, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ACQ, "DATA_DIR", os.path.dirname(ledger))

    r = ACQ.upsert(2024, "广东", "school_lines", "collected",
                   source_url="https://eea.gd.gov.cn/x", operator="tester")
    assert r["ok"] and r["count"] == 1
    # 幂等：同格更新不新增
    r2 = ACQ.upsert(2024, "广东", "school_lines", "ingested", operator="tester")
    assert r2["ok"] and r2["count"] == 1
    assert r2["entry"]["status"] == "ingested"
    # 非法参数拒收
    assert not ACQ.upsert(2024, "广东", "bogus", "pending")["ok"]
    assert not ACQ.upsert(2024, "广东", "school_lines", "bogus")["ok"]
    assert not ACQ.upsert(2024, "火星", "school_lines", "pending")["ok"]

    m = ACQ.matrix()
    cell = m["cells"].get("2024|广东|school_lines")
    assert cell and cell["status"] == "ingested" and cell["operator"] == "tester"
    # 库内实测：一分段落盘文件应自动标定（广东 2024 有落盘）
    rt_cell = m["cells"].get("2024|广东|rank_table")
    assert rt_cell and rt_cell["status"] == "ingested", "实测覆盖应自动标定格子"
    assert 2024 in m["years"]


def test_acquisition_api(monkeypatch):
    ledger_dir = _tmpdir("acq-api")
    monkeypatch.setattr(ACQ, "LEDGER_PATH", os.path.join(ledger_dir, "acquisition_ledger.json"))
    monkeypatch.setattr(ACQ, "DATA_DIR", ledger_dir)
    h = ready_headers(c)
    r = c.get("/api/admin/acquisition", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["provinces"] and body["categories"]

    r2 = c.post("/api/admin/acquisition", headers=h, json={
        "year": 2024, "province": "河南", "category": "rank_table", "status": "ingested",
        "source_url": "https://haeea.cn/x", "note": "api 落库"})
    assert r2.status_code == 200, r2.text
    r3 = c.post("/api/admin/acquisition", headers=h, json={
        "year": 2024, "province": "河南", "category": "bogus", "status": "pending"})
    assert r3.status_code == 400


# ---------------------------------------------------------------- 数据体检 + 原表留档

def test_health_report_structure_and_official_cross_check(monkeypatch):
    ledger_dir = _tmpdir("quality")
    monkeypatch.setattr(ACQ, "LEDGER_PATH", os.path.join(ledger_dir, "acquisition_ledger.json"))
    _cleanup_lines()
    try:
        rep = DQ.health_report()
        for key in ("school_lines", "official_sources", "official_landing",
                    "cross_check", "year_over_year_anomalies", "seed", "generated_at"):
            assert key in rep
        assert rep["cross_check"]["warnings"] == 0

        # 落一行与一分一段表矛盾的 official 行 → 体检应报出来
        if _rank_table_available():
            with session_scope() as s:
                s.add(_mkrow("矛盾大学", "01", 999999, "official", year=2024,
                             province="广东", subject="物理类", score=665))
            rep2 = DQ.health_report()
            assert rep2["cross_check"]["warnings"] >= 1
            assert any(s["university"] == "矛盾大学"
                       for s in rep2["cross_check"]["samples"])
    finally:
        _cleanup_lines()


def test_import_official_table_archives_raw_file(monkeypatch):
    tmp = _tmpdir("archive")
    monkeypatch.setattr(SL, "OFFICIAL_REGISTRY", os.path.join(tmp, "sources.json"))
    monkeypatch.setattr(SL, "OFFICIAL_ARCHIVE_DIR", os.path.join(tmp, "archive"))
    _cleanup_lines()
    try:
        raw = json.dumps({
            "meta": {"year": 2024, "province": "广东", "subject": "物理类",
                     "source_url": "https://eea.gd.gov.cn/archive-test",
                     "source_org": "广东省教育考试院"},
            "rows": [{"university": "华南理工大学", "group_code": "202",
                      "min_score": 610, "min_rank": 13000}],
        }).encode("utf-8")
        rep = SL.import_official_table(raw, "gd_2024.json", {}, dry_run=False,
                                       operator="test", register=True, archive=True)
        assert rep["ok"] and rep["inserted"] == 1
        assert rep.get("archive"), "落库成功应返回存档路径"
        archive_path = os.path.join(SL.DATA_DIR, rep["archive"])
        assert os.path.exists(archive_path)
        with open(archive_path, "rb") as f:
            assert f.read() == raw
        reg = SL.official_registry()
        assert reg["count"] == 1 and reg["files"][0].get("archive") == rep["archive"]
    finally:
        _cleanup_lines()


# ---------------------------------------------------------------- 体检 API

def test_data_quality_api(monkeypatch):
    monkeypatch.setattr(ACQ, "LEDGER_PATH",
                        os.path.join(_tmpdir("quality-api"), "acquisition_ledger.json"))
    r = c.get("/api/admin/data-quality", headers=ready_headers(c))
    assert r.status_code == 200
    assert r.json()["ok"] is True
