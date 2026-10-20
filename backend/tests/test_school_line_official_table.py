"""官方原表解析落库 + 溯源登记测试（S8-A）。

S7-A 做的是「通道」（目录 / 校验 / 端点），S8-A 补的是**机器可读原表的解析与投喂闭环**：
省考试院公布的投档情况表（CSV / XLSX）列名各异，本模块按别名识别表头，解析后走同一套
强校验落为 ``official``，并把「哪个文件、哪条链接、多少行」写进溯源台账。

重点是这条链路上不能出现「来路不明却标成官方」的行：
  - 没有来源链接 → 解析出来也全部拒收；
  - 落库成功 → 必须留下可审计的台账（文件名 + sha256 + 来源链接）。

台账用临时路径，避免污染仓库内的 backend/data/official/sources.json。
"""
import json
import os
import tempfile

import main
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from db import session_scope
from db.models import DataChange, SchoolLine
from services import school_lines as SL
from tests.helpers import ready_headers

c = TestClient(main.app)

TEST_YEAR = 2096          # 官方原表测试专用年份
GD_URL = "https://eea.gd.gov.cn/zwgk/sjfb/tjsj/content/post_4444840.html"

# 省考试院「投档情况表」常见写法：投档最低分 / 投档最低排位 / 院校专业组
CSV_GD = (
    "院校名称,院校专业组,投档最低分,投档最低排位,批次\n"
    "中山大学,201,624,8000,本科批\n"
    "华南理工大学,202,610,13000,本科批\n"
    "野鸡大学,999,500,999999,本科批\n"
).encode("utf-8")


def _cleanup():
    with session_scope() as s:
        s.execute(delete(SchoolLine).where(SchoolLine.year == TEST_YEAR))
        s.execute(delete(DataChange).where(DataChange.dataset == "school_lines"))
    SL.invalidate_cache()


def _tmp_registry():
    """把溯源台账指向临时文件，测完恢复（仓库内的台账不应被测试写脏）。"""
    base = os.path.join(os.path.dirname(__file__), ".bk_tmp")
    os.makedirs(base, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="registry_", suffix=".json", dir=base)
    os.close(fd)
    os.unlink(path)
    return path


def test_parse_official_table_reads_exam_authority_headers():
    """省考试院原表的「投档最低分 / 投档最低排位」列名必须能被识别。"""
    parsed = SL.parse_official_table(
        CSV_GD, "gd_2024.csv",
        defaults={"year": TEST_YEAR, "province": "广东", "subject": "物理类",
                  "source_url": GD_URL})
    assert parsed["ok"] is True and parsed["format"] == "csv"
    assert parsed["parsed"] == 3
    zs = [r for r in parsed["rows"] if r.get("university") == "中山大学"][0]
    assert zs["min_score"] == 624 and zs["min_rank"] == 8000
    assert zs["group_code"] == "201" and zs["batch"] == "本科批"
    assert zs["source_url"] == GD_URL, "文件级来源链接应灌进每一行"


def test_parse_official_table_rejects_unrecognizable_header():
    parsed = SL.parse_official_table("序号,备注\n1,说明\n".encode("utf-8"), "bad.csv")
    assert parsed["ok"] is False
    assert "表头" in parsed["error"]


def test_import_official_table_dry_run_does_not_write():
    _cleanup()
    rep = SL.import_official_table(
        CSV_GD, "gd_2024.csv",
        defaults={"year": TEST_YEAR, "province": "广东", "subject": "物理类",
                  "source_url": GD_URL},
        dry_run=True)
    # 3 行里「野鸡大学」匹配不上教育部名单 → 拒收
    assert rep["ok"] is True and rep["parsed"] == 3
    assert rep["accepted"] == 2 and rep["rejected"] == 1
    assert rep["inserted"] == 0
    with session_scope() as s:
        assert s.scalar(select(SchoolLine).where(SchoolLine.year == TEST_YEAR)) is None
    assert "registry" not in rep, "dry-run 不该登记溯源台账"


def test_import_official_table_commit_writes_registry():
    """落库成功必须留下可审计台账：文件名 / sha256 / 省 / 年 / 来源链接 / 行数。"""
    _cleanup()
    original = SL.OFFICIAL_REGISTRY
    SL.OFFICIAL_REGISTRY = _tmp_registry()
    try:
        rep = SL.import_official_table(
            CSV_GD, "gd_2024.csv",
            defaults={"year": TEST_YEAR, "province": "广东", "subject": "物理类",
                      "source_url": GD_URL, "source_org": "广东省教育考试院"},
            dry_run=False, operator="tester")
        assert rep["inserted"] == 2 and rep["rejected"] == 1
        with session_scope() as s:
            saved = s.scalars(select(SchoolLine).where(SchoolLine.year == TEST_YEAR)).all()
            assert len(saved) == 2
            assert all(r.data_source == "official" and r.source_url == GD_URL for r in saved)

        reg = SL.official_registry()
        assert reg["count"] == 1
        e = reg["files"][0]
        assert e["file"] == "gd_2024.csv" and e["province"] == "广东"
        assert e["year"] == TEST_YEAR and e["subject"] == "物理类"
        assert e["rows"] == 2 and e["rejected"] == 1
        assert e["source_url"] == GD_URL
        assert len(e["sha256"]) == 64, "台账必须带原表校验和，便于事后核对"

        # 重复登记按文件名去重，不产生重复条目
        SL.import_official_table(
            CSV_GD, "gd_2024.csv",
            defaults={"year": TEST_YEAR, "province": "广东", "subject": "物理类",
                      "source_url": GD_URL},
            dry_run=False)
        assert SL.official_registry()["count"] == 1
    finally:
        SL.OFFICIAL_REGISTRY = original
        _cleanup()


def test_import_official_table_without_source_url_rejects_all():
    """没有来源链接的原表：解析得出行，但一行都不落——official 不能来路不明。"""
    _cleanup()
    rep = SL.import_official_table(
        CSV_GD, "gd_2024.csv",
        defaults={"year": TEST_YEAR, "province": "广东", "subject": "物理类"},
        dry_run=False)
    assert rep["accepted"] == 0 and rep["rejected"] == 3
    assert any("source_url" in r for r in rep["rejected_samples"][0]["reasons"])
    with session_scope() as s:
        assert s.scalar(select(SchoolLine).where(SchoolLine.year == TEST_YEAR)) is None
    _cleanup()


def test_import_official_table_json():
    """JSON 原表：meta 里的默认值（年/省/来源）应被采纳。"""
    _cleanup()
    doc = {"meta": {"year": TEST_YEAR, "province": "广东", "subject": "物理类",
                    "source_url": GD_URL},
           "rows": [{"university": "中山大学", "group_code": "201",
                     "min_score": 624, "min_rank": 8000}]}
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    original = SL.OFFICIAL_REGISTRY
    SL.OFFICIAL_REGISTRY = _tmp_registry()   # 别把测试登记写进仓库里的台账
    try:
        rep = SL.import_official_table(raw, "gd_2024.json", dry_run=False)
        assert rep["format"] == "json" and rep["accepted"] == 1 and rep["inserted"] == 1
        assert SL.official_registry()["count"] == 1
    finally:
        SL.OFFICIAL_REGISTRY = original
        _cleanup()


def test_admin_official_sources_endpoint():
    """管理端可读溯源台账（S8-A）。"""
    headers = ready_headers(c)
    r = c.get("/api/admin/school-lines/official-sources", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and "count" in body and "files" in body


def test_admin_official_file_import_reports_parsed_rows():
    """上传原表落库后，响应要说明解析了多少行、能否溯源。"""
    _cleanup()
    headers = ready_headers(c)
    r = c.post("/api/admin/school-lines/import-official-file",
               headers=headers,
               files={"file": ("gd.csv", CSV_GD, "text/csv")},
               data={"year": str(TEST_YEAR), "province": "广东", "subject": "物理类",
                     "dry_run": "true", "source_url": GD_URL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parsed"] == 3 and body["parsed_rows"] == 3
    assert body["accepted"] == 2 and body["rejected"] == 1
    _cleanup()


def test_health_reports_official_sources_and_evidence_gate():
    """health 同时上报官方溯源台账与证据门槛分布（S8-A / S8-B）。"""
    body = c.get("/api/health").json()
    sl = body["school_lines"]
    assert "official_sources" in sl and "files" in sl["official_sources"]
    gate = sl["evidence_gate"]
    assert gate["combos"] > 0
    assert set(gate["bands"]) == {"full", "thin", "none"}
    assert set(gate["thresholds"]) == {"thin", "full", "refute"}
