"""官方逐校投档线落库通道测试（S7-A）。

S6 的官方数据只到「985/211 层次入门线」（6 省 22 行）。S7-A 把官方通道扩到
**逐校逐专业组**：运营把省考试院投档原表放进 backend/data/official/ 或经管理端上传，
落为 school_lines 的 official 行。

``official`` 是可信度最高的标签，所以通道的校验比普通导入更严——本文件的用例重点
验证「宁可少落，也不能把来路不明的行标成官方」：
缺来源链接 / 省份或年份异常 / 分数位次越界 / 校名匹配不上 → 整行拒收并给出原因。

本文件用例都用年份 2097 精确清理自己写入的行，避免污染其它用例对权威分级的断言。
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

TEST_YEAR = 2097          # 官方落库测试专用年份
GD_URL = "https://eea.gd.gov.cn/zwgk/sjfb/tjsj/content/post_4444840.html"


def _cleanup_official():
    """删掉本文件写入的 official 行，恢复「无 official 校线」基线。"""
    with session_scope() as s:
        s.execute(delete(SchoolLine).where(SchoolLine.year == TEST_YEAR))
        s.execute(delete(SchoolLine).where(
            SchoolLine.data_source == "official",
            SchoolLine.group_code.in_(("985", "211"))))
        s.execute(delete(DataChange).where(DataChange.dataset == "school_lines"))
    SL.invalidate_cache()


def _mk_tmp_dir() -> str:
    """项目内临时目录（绕过沙箱对 pytest 默认 /private/tmp 根目录的 mkdir 拦截）。"""
    base = os.path.join(os.path.dirname(__file__), ".bk_tmp")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="official_", dir=base)


def _good_row(**kw) -> dict:
    row = {"university": "中山大学", "province": "广东", "subject": "物理类",
           "year": TEST_YEAR, "group_code": "201", "min_score": 624, "min_rank": 8000,
           "source_url": GD_URL}
    row.update(kw)
    return row


def test_official_landing_dir_ships_empty_by_design():
    """仓库不预置官方数据：落地区有说明文档，但不放任何数据文件。"""
    assert os.path.isdir(SL.OFFICIAL_DIR), "落地区应随仓库提交（含 README）"
    landing = SL.official_landing_rows()
    assert landing["dir_exists"] is True
    assert landing["accepted_count"] == 0, "仓库不得预置来路不明的官方数据"
    assert os.path.exists(os.path.join(SL.OFFICIAL_DIR, "README.md"))


def test_validate_official_rejects_missing_source_url():
    """缺官方来源链接 → 整行拒收（官方口径必须可回溯）。"""
    res = SL.validate_official_rows([_good_row(source_url="")])
    assert res["accepted"] == [] and res["rejected"]
    assert any("source_url" in r for r in res["rejected"][0]["reasons"])

    res2 = SL.validate_official_rows([_good_row(source_url="见附件")])
    assert res2["accepted"] == []


def test_validate_official_rejects_bad_values():
    res = SL.validate_official_rows([
        _good_row(min_score=9999),                       # 分数越界
        _good_row(province="火星"),                       # 省份无法识别
        _good_row(year=1899),                            # 年份异常
        _good_row(university="不存在的野鸡大学"),           # 校名匹配不上
        _good_row(min_score=None, min_rank=None),         # 分数位次全缺
    ])
    assert res["accepted"] == []
    assert len(res["rejected"]) == 5
    reasons = "；".join(r for item in res["rejected"] for r in item["reasons"])
    for key in ("越界", "省份", "年份", "教育部名单", "全缺"):
        assert key in reasons


def test_validate_official_accepts_aliases_and_defaults():
    """中文表头别名 + 文件级默认值（年份/省份/来源）都应生效。"""
    res = SL.validate_official_rows(
        [{"院校名称": "华中科技大学", "最低分": 630, "最低位次": 6000, "专业组": "203"}],
        defaults={"year": TEST_YEAR, "province": "广东", "subject": "物理类",
                  "source_url": GD_URL})
    assert len(res["accepted"]) == 1
    row = res["accepted"][0]
    assert row["university"] == "华中科技大学"
    assert row["year"] == TEST_YEAR and row["province"] == "广东"
    assert row["data_source"] == "official"
    assert row["trusted_host"] is True


def test_provenance_warning_for_untrusted_host():
    """来源域名不像考试院机构 → 仍落库但在备注里留痕，交由人工复核。"""
    res = SL.validate_official_rows([_good_row(source_url="https://example.com/gd.csv")])
    assert len(res["accepted"]) == 1
    assert res["accepted"][0]["trusted_host"] is False
    assert "非考试院机构" in res["accepted"][0]["note"]
    assert len(res["provenance_warnings"]) == 1


def test_import_official_dry_run_then_commit_and_idempotent():
    _cleanup_official()
    rows = [_good_row(group_code="201"),
            _good_row(university="华南理工大学", group_code="202", min_score=610, min_rank=13000)]

    dry = SL.import_official(rows, dry_run=True)
    assert dry["accepted"] == 2 and dry["inserted"] == 0
    with session_scope() as s:
        assert s.scalar(select(SchoolLine).where(SchoolLine.year == TEST_YEAR)) is None

    first = SL.import_official(rows, dry_run=False, operator="tester")
    assert first["inserted"] == 2 and first["rejected"] == 0
    with session_scope() as s:
        saved = s.scalars(select(SchoolLine).where(SchoolLine.year == TEST_YEAR)).all()
        assert len(saved) == 2
        assert all(r.data_source == "official" for r in saved)
        assert all(r.source_url == GD_URL for r in saved)
        assert all(r.operator == "tester" for r in saved)
        assert sorted(r.group_code for r in saved) == ["201", "202"]

    again = SL.import_official(rows, dry_run=False)
    assert again["inserted"] == 0 and again["unchanged"] == 2

    # 变化的行会被更新（不是无脑覆盖）
    changed = SL.import_official([_good_row(group_code="201", min_score=650)], dry_run=False)
    assert changed["updated"] == 1 and changed["inserted"] == 0
    _cleanup_official()
    assert SL.source_counts()["official"] == 0


def test_official_landing_rows_reads_json_file():
    """放进落地区的 JSON 原表（带 meta 默认值）能被识别。"""
    d = _mk_tmp_dir()
    with open(os.path.join(d, "gd_2024.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": {"year": TEST_YEAR, "province": "广东", "subject": "物理类",
                            "source_org": "广东省教育考试院", "source_url": GD_URL},
                   "rows": [{"university": "中山大学", "group_code": "201",
                             "min_score": 624, "min_rank": 8000},
                            {"university": "不存在大学", "group_code": "999", "min_score": 500}]},
                  f, ensure_ascii=False)
    landing = SL.official_landing_rows(directory=d)
    assert landing["accepted_count"] == 1
    assert landing["rejected_count"] == 1
    assert landing["files"][0]["accepted"] == 1
    assert landing["files"][0]["rejected"] == 1
    assert landing["accepted"][0]["university"] == "中山大学"


def test_official_landing_rows_flags_csv_without_source():
    """落地区里的 CSV 没有来源链接 → 全部拒收，不静默降级。"""
    d = _mk_tmp_dir()
    with open(os.path.join(d, "no_source.csv"), "w", encoding="utf-8") as f:
        f.write("院校名称,最低分,最低位次,专业组\n中山大学,624,8000,201\n")
    landing = SL.official_landing_rows(directory=d)
    assert landing["accepted_count"] == 0
    assert landing["rejected_count"] == 1
    assert any("source_url" in r for r in landing["rejected"][0]["reasons"])


def test_admin_official_endpoints():
    """管理端：official-status 只读；import-official 默认不写库；上传缺来源链接报 400。"""
    _cleanup_official()
    headers = ready_headers(c)

    st = c.get("/api/admin/school-lines/official-status", headers=headers)
    assert st.status_code == 200, st.text
    body = st.json()
    assert body["ok"] is True and "accepted_count" in body

    dry = c.post("/api/admin/school-lines/import-official",
                 json={"rows": [_good_row()], "dry_run": True}, headers=headers)
    assert dry.status_code == 200, dry.text
    assert dry.json()["accepted"] == 1
    with session_scope() as s:
        assert s.scalar(select(SchoolLine).where(SchoolLine.year == TEST_YEAR)) is None

    csv_bytes = "院校名称,最低分,最低位次,专业组\n中山大学,624,8000,201\n".encode("utf-8")
    no_url = c.post("/api/admin/school-lines/import-official-file",
                    headers=headers,
                    files={"file": ("gd.csv", csv_bytes, "text/csv")},
                    data={"year": str(TEST_YEAR), "province": "广东", "subject": "物理类",
                          "dry_run": "true", "source_url": ""})
    assert no_url.status_code == 400, no_url.text

    ok = c.post("/api/admin/school-lines/import-official-file",
                headers=headers,
                files={"file": ("gd.csv", csv_bytes, "text/csv")},
                data={"year": str(TEST_YEAR), "province": "广东", "subject": "物理类",
                      "dry_run": "true", "source_url": GD_URL})
    assert ok.status_code == 200, ok.text
    assert ok.json()["accepted"] == 1
    _cleanup_official()


def test_health_reports_official_landing_channel():
    """health 暴露官方落库通道：目录是否就绪 + 待落库行数。"""
    body = c.get("/api/health").json()
    landing = body["school_lines"]["official_landing"]
    assert landing["dir_ready"] is True
    assert landing["pending_rows"] == 0
    seed = body["school_lines"]["seed"]
    assert seed["available"] is True and seed["rows"] > 0
    assert seed["compressed"] is True, "S7-B：仓库只提交 gzip 种子"
    assert seed["sha256_ok"] is True
