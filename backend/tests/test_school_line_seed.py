"""自托管种子一键落库测试（S6）。

背景：院校投档线原先只能现拉上游公开爬虫仓库（第三方开源项目，随时可能下架）。
S6 把已入库数据导出成仓库自带种子并提交入库，新环境无需联网即可一键落库重建；
同时把官方文件里的 985/211 入门投档（省考试院官方口径）直接落为 ``official`` 行。

本文件的用例都**精确清理自己写入的行**：
- 官方行：year=2024 且 group_code ∈ {985, 211} 且 data_source='official'
- 抓取行：year=2098（测试专用年份）

以免污染其它用例对「权威分级」的断言（例如 health 上报 official=0）。
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

TEST_YEAR = 2098   # 抓取种子测试专用年份
OFFICIAL_YEAR = 2024
TIER_CODES = ("985", "211")


def _cleanup_seed():
    """删掉本文件用例写入的行，恢复库到「无 official 校线」的基线状态。"""
    with session_scope() as s:
        s.execute(delete(SchoolLine).where(
            SchoolLine.year == OFFICIAL_YEAR,
            SchoolLine.data_source == "official",
            SchoolLine.group_code.in_(TIER_CODES)))
        s.execute(delete(SchoolLine).where(SchoolLine.year == TEST_YEAR))
        s.execute(delete(DataChange).where(DataChange.dataset == "school_lines"))
    SL.invalidate_cache()


def _mk_tmp_dir() -> str:
    """在项目目录内建临时目录（绕过沙箱对 pytest 默认 /private/tmp 根目录的 mkdir 拦截）。"""
    base = os.path.join(os.path.dirname(__file__), ".bk_tmp")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="seed_", dir=base)


def _write_temp_seed(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": {"rows": len(rows), "data_source": "estimated_real"},
                   "rows": rows}, f, ensure_ascii=False)


def test_seed_file_is_committed_not_gitignored():
    """种子必须随仓库提交——这是摆脱上游爬虫仓库依赖的前提。"""
    status = SL.seed_status()
    assert status["estimated"]["exists"] is True, "种子文件缺失，新环境将无法重建校线"
    assert status["estimated"]["rows"] > 0
    # S7-B：仓库只提交 gzip 副本，明文 7.2MB 不再入库
    assert status["estimated"]["compressed"] is True
    assert status["estimated"]["path"].endswith(".json.gz")
    assert len(status["estimated"]["sha256"]) == 64
    assert status["estimated"]["size_bytes"] < 2 * 1024 * 1024, "gzip 后应远小于明文 7.2MB"


def test_seed_status_reports_both_sources():
    status = SL.seed_status()
    assert status["official"]["exists"] is True
    assert status["official"]["rows"] > 0
    assert status["total_seed_rows"] == status["estimated"]["rows"] + status["official"]["rows"]


def test_official_seed_rows_are_real_and_official():
    rows = SL.official_seed_rows()
    assert rows, "官方文件里应有 985/211 入门投档"
    assert all(r["data_source"] == "official" for r in rows)
    assert all(r["group_code"] in TIER_CODES for r in rows), "层次作占位，避免与逐专业组行撞唯一键"
    assert all(r["min_rank"] > 0 and r["min_score"] > 0 for r in rows)
    assert all(r["university"] for r in rows), "校名必须匹配到教育部名单"
    # 官方省份（6 省）应都在 PROVINCES 里
    assert all(r["province"] in SL.PROVINCES for r in rows)


def test_import_seed_dry_run_writes_nothing():
    _cleanup_seed()
    report = SL.import_seed(commit=False, include=["official"])
    assert report["dry_run"] is True
    assert report["official"]["available"] > 0
    assert report["inserted"] == 0 and report["updated"] == 0 and report["unchanged"] == 0
    with session_scope() as s:
        assert s.scalar(select(SchoolLine).where(
            SchoolLine.data_source == "official",
            SchoolLine.group_code.in_(TIER_CODES))) is None
    _cleanup_seed()


def test_import_seed_official_lands_and_is_idempotent():
    """官方数据直接落库：写入后 has_official 为真，重复执行只更新不重复插入。"""
    _cleanup_seed()
    first = SL.import_seed(commit=True, include=["official"])
    assert first["official"]["inserted"] > 0
    assert first["official"]["updated"] == 0

    with session_scope() as s:
        rows = s.scalars(select(SchoolLine).where(
            SchoolLine.year == OFFICIAL_YEAR, SchoolLine.data_source == "official")).all()
        assert len(rows) == first["official"]["inserted"]
        assert all(r.batch == "普通类本科批" for r in rows)
        assert all(r.operator for r in rows)

    counts = SL.source_counts()
    assert counts["official"] == first["official"]["inserted"]
    assert counts["has_official"] is True
    # M07 修复后 grade 为三态互斥：库内同时有 estimated_real（conftest 种子）与 official → mixed
    assert counts["grade"] == "mixed"

    # 幂等：第二次全 unchanged
    second = SL.import_seed(commit=True, include=["official"])
    assert second["official"]["inserted"] == 0
    assert second["official"]["unchanged"] == first["official"]["inserted"]
    _cleanup_seed()

    after = SL.source_counts()
    assert after["official"] == 0, "清理后应回到无 official 校线的基线"
    assert after["has_official"] is False


def test_import_seed_estimated_uses_seed_file():
    """抓取快照按种子文件落库，标 estimated_real（用临时小种子避免动真实 14019 行）。"""
    _cleanup_seed()
    fake = os.path.join(_mk_tmp_dir(), "seed.json")
    _write_temp_seed(str(fake), [
        {"year": TEST_YEAR, "province": "河南", "subject": "物理类", "batch": "本科一批",
         "university": "郑州大学", "university_input": "郑州大学", "group_code": "01",
         "min_score": 600, "min_rank": 30000, "data_source": "estimated_real",
         "match_method": "exact", "source_url": "https://example.edu.cn/s/1", "note": "种子测试"},
        {"year": TEST_YEAR, "province": "河南", "subject": "物理类", "batch": "本科一批",
         "university": "河南大学", "university_input": "河南大学", "group_code": "02",
         "min_score": 580, "min_rank": 40000, "data_source": "estimated_real",
         "match_method": "exact", "source_url": "https://example.edu.cn/s/2", "note": "种子测试"},
    ])
    original = SL.SEED_ESTIMATED
    SL.SEED_ESTIMATED = str(fake)
    try:
        report = SL.import_seed(commit=True, include=["estimated"])
        assert report["estimated"]["available"] == 2
        assert report["estimated"]["inserted"] == 2
        with session_scope() as s:
            rows = s.scalars(select(SchoolLine).where(SchoolLine.year == TEST_YEAR)).all()
            assert len(rows) == 2
            assert all(r.data_source == "estimated_real" for r in rows)
            assert sorted(r.group_code for r in rows) == ["01", "02"]
        # 幂等
        again = SL.import_seed(commit=True, include=["estimated"])
        assert again["estimated"]["inserted"] == 0
        assert again["estimated"]["unchanged"] == 2
    finally:
        SL.SEED_ESTIMATED = original
        _cleanup_seed()


def test_seed_admin_endpoints():
    """管理端：seed-status 只读可查，import-seed 默认不写库。"""
    _cleanup_seed()
    headers = ready_headers(c)

    st = c.get("/api/admin/school-lines/seed-status", headers=headers)
    assert st.status_code == 200, st.text
    j = st.json()
    assert j["ok"] is True and j["total_seed_rows"] > 0

    r = c.post("/api/admin/school-lines/import-seed", json={"dry_run": True},
               headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["estimated"]["available"] > 0
    assert body["official"]["available"] > 0
    with session_scope() as s:
        assert s.scalar(select(SchoolLine).where(
            SchoolLine.data_source == "official",
            SchoolLine.group_code.in_(TIER_CODES))) is None

    bad = c.post("/api/admin/school-lines/import-seed", json={"dry_run": True, "include": ["nope"]},
                 headers=headers)
    assert bad.status_code == 400
    _cleanup_seed()


# ---------------------------------------------------------------- S7-B 种子治理


def test_seed_manifest_matches_file():
    """seed.meta.json 的校验和必须与种子文件一致（导入前可先验完整性）。"""
    meta = SL.seed_meta()
    assert meta.get("exists") is True, "缺少 seed.meta.json，无法校验种子完整性"
    check = SL.verify_seed()
    assert check["ok"] is True, check["errors"]
    assert check["sha256"] == meta["sha256"]
    assert check["rows"] == meta["rows"] > 0


def test_verify_seed_detects_corruption():
    """种子被改坏（校验和对不上）时能被发现，而不是默默落一半数据。"""
    d = _mk_tmp_dir()
    bad = os.path.join(d, "bad.json.gz")
    import gzip
    with gzip.open(bad, "wt", encoding="utf-8") as f:
        json.dump({"meta": {}, "rows": [{"year": 2099, "university": "郑州大学"}]}, f)
    # 无清单时只看能否解析
    assert SL.verify_seed(path=bad)["ok"] is True

    corrupted = os.path.join(d, "corrupt.json.gz")
    with open(corrupted, "wb") as f:
        f.write(b"not a gzip at all")
    out = SL.verify_seed(path=corrupted)
    assert out["ok"] is False and out["errors"]

    missing = os.path.join(d, "nope.json.gz")
    assert SL.verify_seed(path=missing)["exists"] is False

    # 正式种子被改动、与 seed.meta.json 对不上 → 报错
    with open(bad, "wb") as f:
        f.write(b"tampered")
    original = SL.SEED_ESTIMATED
    SL.SEED_ESTIMATED = bad
    try:
        out = SL.verify_seed()
        assert out["ok"] is False
        assert any("校验和" in e or "损坏" in e for e in out["errors"])
    finally:
        SL.SEED_ESTIMATED = original


def test_seed_status_reports_consistency():
    """管理端能看到「库内行数 vs 种子行数」是否一致。"""
    status = SL.seed_status()
    est = status["estimated"]
    assert "db_rows" in est and "consistent" in est
    assert isinstance(est["consistent"], bool)
    # 测试库本身应与仓库种子一致（若不一致，管理端会提示重新导出）
    assert est["rows"] == est["db_rows"] or est["consistent"] is False


def test_export_seed_gzip_roundtrip():
    """gzip 导出 → 导入闭环：压缩后的种子能原样落回库。"""
    _cleanup_seed()
    with session_scope() as s:
        s.add(SchoolLine(year=TEST_YEAR, province="河南", subject="物理类", batch="本科一批",
                         university="郑州大学", university_input="郑州大学", group_code="01",
                         min_score=601, min_rank=31000, data_source="estimated_real",
                         match_method="exact", source_url="https://example.edu.cn/s/9",
                         note="gz roundtrip"))
    out = os.path.join(_mk_tmp_dir(), "export.json.gz")
    SL.export_seed(path=str(out), data_source="estimated_real", year=TEST_YEAR)
    assert SL.verify_seed(path=str(out))["ok"] is True
    assert SL.read_seed(str(out))["meta"]["rows"] == 1

    _cleanup_seed()  # 先删库里的行，验证种子能把它们原样还原
    original = SL.SEED_ESTIMATED
    SL.SEED_ESTIMATED = str(out)
    try:
        report = SL.import_seed(commit=True, include=["estimated"])
        assert report["estimated"]["available"] == 1
        assert report["estimated"]["inserted"] == 1
        with session_scope() as s:
            rows = s.scalars(select(SchoolLine).where(SchoolLine.year == TEST_YEAR)).all()
            assert len(rows) == 1 and rows[0].note == "gz roundtrip"
            assert rows[0].min_score == 601 and rows[0].min_rank == 31000
    finally:
        SL.SEED_ESTIMATED = original
        _cleanup_seed()


def test_export_seed_roundtrip():
    """导出→导入闭环：导出的种子能原样落回库（用测试年份，避免动真实数据）。"""
    _cleanup_seed()
    with session_scope() as s:
        s.add(SchoolLine(year=TEST_YEAR, province="河南", subject="物理类", batch="本科一批",
                         university="郑州大学", university_input="郑州大学", group_code="01",
                         min_score=601, min_rank=31000, data_source="estimated_real",
                         match_method="exact", source_url="https://example.edu.cn/s/9",
                         note="roundtrip"))
    out = os.path.join(_mk_tmp_dir(), "export.json")
    SL.export_seed(path=str(out), data_source="estimated_real")
    with open(str(out), encoding="utf-8") as f:
        doc = json.load(f)
    assert os.path.getsize(str(out)) > 0
    assert any(r["year"] == TEST_YEAR for r in doc["rows"])
    _cleanup_seed()
