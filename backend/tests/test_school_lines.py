"""院校投档线导入测试（D1）：名称匹配、表格解析、导入幂等、推荐联动、API。"""
import io
import json
import uuid

import main
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from db import session_scope
from db.models import DataChange, SchoolLine
from services import school_lines as SL
from tests.helpers import ready_headers

c = TestClient(main.app)

YEAR = 2098          # 测试专用年份，避免与真实数据冲突
PROVINCE = "河南"
SUBJECT = "物理类"

CSV = (
    "2024 年河南省普通高校招生本科一批投档线（测试样例）\n"
    "院校名称,最低分,最低位次,专业组,批次\n"
    "清华大学,690,120,01,本科一批\n"
    "郑州大学（中外合作）,600,30000,02,本科一批\n"
    "不存在大学XYZ,500,100000,01,本科一批\n"
)


def _cleanup():
    with session_scope() as s:
        s.execute(delete(SchoolLine).where(SchoolLine.year == YEAR))
        s.execute(delete(DataChange).where(DataChange.dataset == "school_lines"))
    SL.invalidate_cache()


def _import(raw: bytes = CSV.encode("utf-8"), filename="lines.csv", dry_run=True, mode="merge",
            extra=None):
    data = {"year": YEAR, "province": PROVINCE, "subject": SUBJECT,
            "source_url": "https://example.edu.cn/lines", "mode": mode,
            "dry_run": "true" if dry_run else "false"}
    data.update(extra or {})
    return c.post("/api/admin/school-lines/import", data=data,
                  files={"file": (filename, raw, "text/csv")}, headers=ready_headers(c))


def test_normalize_and_match_university():
    assert SL.norm_text(" 清华 大学 ") == "清华大学"
    assert SL.clean_university("郑州大学（中外合作）") == "郑州大学"
    assert SL.clean_university("北京大学(较高收费)(单列)") == "北京大学"
    name, method, score = SL.match_university("清华大学")
    assert name == "清华大学" and method in ("exact", "normalized") and score >= 0.98
    name2, method2, _ = SL.match_university("郑州大学（中外合作）")
    assert name2 == "郑州大学" and method2 in ("exact", "normalized")
    name3, method3, _ = SL.match_university("郑州大学中外合作")
    assert name3 == "郑州大学" and method3 in ("normalized", "contains")


def test_parse_detects_header_after_title_row():
    parsed = SL.parse_table(CSV.encode("utf-8"), "lines.csv")
    assert parsed["ok"] and parsed["header_index"] == 1
    assert parsed["mapping"]["university"] == 0
    assert parsed["mapping"]["min_rank"] == 2


def test_parse_rejects_file_without_required_columns():
    bad = "学校,备注\n清华大学,无\n".encode("utf-8")
    parsed = SL.parse_table(bad, "bad.csv")
    assert parsed["ok"] is False and "未识别到表头" in parsed["error"]


def test_parse_xlsx():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["院校名称", "最低分", "最低位次"])
    ws.append(["清华大学", 690, 120])
    buf = io.BytesIO()
    wb.save(buf)
    parsed = SL.parse_table(buf.getvalue(), "lines.xlsx")
    assert parsed["ok"] and parsed["mapping"]["university"] == 0
    assert len(parsed["rows"]) == 1


def test_dry_run_reports_without_writing():
    _cleanup()
    r = _import()
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["dry_run"] is True
    assert j["total_rows"] == 3
    assert j["valid"] == 2, "匹配不上的行不计入 valid"
    assert j["unmatched_count"] == 1
    assert j["unmatched"][0]["university"] == "不存在大学XYZ"
    with session_scope() as s:
        assert s.scalar(select(SchoolLine).where(SchoolLine.year == YEAR)) is None
    _cleanup()


def test_commit_writes_and_is_idempotent():
    _cleanup()
    first = _import(dry_run=False).json()
    assert first["inserted"] == 2 and first["unmatched_count"] == 1
    with session_scope() as s:
        rows = s.scalars(select(SchoolLine).where(SchoolLine.year == YEAR)).all()
        assert len(rows) == 2
        ts = next(r for r in rows if r.university == "清华大学")
        assert ts.min_score == 690 and ts.min_rank == 120
        assert ts.data_source == "official", "带 source_url 应标记 official"
        assert ts.match_method in ("exact", "normalized")

    second = _import(dry_run=False).json()
    assert second["inserted"] == 0 and second["updated"] == 0 and second["unchanged"] == 2
    _cleanup()


def test_invalid_rows_are_reported_not_written():
    _cleanup()
    bad = (
        "院校名称,最低分,最低位次\n"
        "清华大学,9999,120\n"      # 分数越界
        "郑州大学,600,0\n"          # 位次越界
        "河南大学,,\n"              # 两者都空
    ).encode("utf-8")
    j = _import(raw=bad, dry_run=False).json()
    assert j["inserted"] == 0
    assert j["invalid_count"] == 3
    reasons = " ".join(e for row in j["invalid"] for e in row["errors"])
    assert "分数超出范围" in reasons and "位次超出范围" in reasons
    _cleanup()


def test_replace_mode_removes_stale_rows():
    _cleanup()
    _import(dry_run=False)
    smaller = "院校名称,最低分,最低位次,专业组\n清华大学,690,120,01\n".encode("utf-8")
    j = _import(raw=smaller, dry_run=False, mode="replace").json()
    assert j["deleted"] == 1, "只应删掉文件里没有的郑州大学 02 组"
    with session_scope() as s:
        rows = s.scalars(select(SchoolLine).where(SchoolLine.year == YEAR)).all()
        assert [r.university for r in rows] == ["清华大学"]
    _cleanup()


def test_public_api_query_and_coverage():
    _cleanup()
    _import(dry_run=False)
    r = c.get("/api/school-lines", params={"province": PROVINCE, "subject": SUBJECT, "year": YEAR})
    assert r.status_code == 200
    j = r.json()
    assert j["count"] == 2
    names = {row["university"] for row in j["rows"]}
    assert {"清华大学", "郑州大学"} <= names

    cov = c.get("/api/school-lines/coverage").json()
    assert any(item["year"] == YEAR for item in cov["years"])
    _cleanup()


def test_recommend_attaches_school_line():
    """导入校线后，推荐结果里对应院校应带 min_score/min_rank 且透传真实来源。"""
    _cleanup()
    _import(dry_run=False)
    r = c.get("/api/recommend/schools", params={"province": PROVINCE, "subject": SUBJECT,
                                                "user_rank": 5000, "limit": 50})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["school_line_hits"] >= 1
    hit = next(s for t in j["tiers"] for s in t["schools"] if s["name"] == "清华大学")
    # 导入时带了 source_url，行走 official 口径：来源应透传而非写死 school_line
    assert hit["data_source"] == "official"
    assert hit["min_score"] == 690 and hit["min_rank"] == 120
    assert hit["line_year"] == YEAR
    assert any("已匹配到院校级投档线" in n for n in j["notes"])
    _cleanup()


def test_group_code_kept_apart():
    """同院校不同专业组应各自成行，不互相覆盖。"""
    _cleanup()
    raw = ("院校名称,最低分,最低位次,专业组\n"
           "郑州大学,600,30000,01\n"
           "郑州大学,580,40000,02\n").encode("utf-8")
    j = _import(raw=raw, dry_run=False).json()
    assert j["inserted"] == 2
    with session_scope() as s:
        rows = s.scalars(select(SchoolLine).where(SchoolLine.year == YEAR)).all()
        assert sorted(r.group_code for r in rows) == ["01", "02"]
    _cleanup()
