"""一分一段表（rank_tables）测试。

覆盖：
1. 落盘 JSON 的结构/溯源/口径不变量（score 降序、累计=前项+本段）；
2. 行重建纯函数 ``_rows_from_lines``（含跨版本式样与噪声行）；
3. 校验器 ``validate_rows``（好数据过 / 坏数据整份拒收）；
4. 服务层 years/doc/lookup（含非精确分数取下界）；
5. 落库脚本整组替换幂等 + 缺 source_url 拒收；
6. API 三端点。

注意：解析器对真实 PDF 的端到端验证依赖网络与体积，不在单测内做；
落盘 JSON 本身就是解析结果的快照，其不变量由第 1 组测试守护。
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

import os

os.environ.setdefault("XUEFENG_DB_PATH", "/tmp/xf_rank_tables_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from scripts.scrape_rank_tables import _rows_from_lines, validate_rows  # noqa: E402
from services import rank_tables as RT  # noqa: E402

c = None  # 延迟创建（等环境变量生效后再 import main）


def _client():
    global c
    if c is None:
        import main as m

        c = TestClient(m.app)
    return c


# ---------------------------------------------------------------------------
# 1. 落盘 JSON 不变量（repo 内真实数据快照）
# ---------------------------------------------------------------------------
def _landed_docs():
    out = []
    data = _BACKEND / "data" / "rank_tables"
    if data.is_dir():
        for f in sorted(data.glob("*/*.json")):
            out.append((f, json.loads(f.read_text(encoding="utf-8"))))
    return out


def test_landed_json_structure_and_invariants():
    docs = _landed_docs()
    assert docs, "data/rank_tables 下应有已落盘的官方数据（广东 2022-2026 至少一年）"
    for f, doc in docs:
        meta = doc["meta"]
        assert meta["data_source"] == "official", f
        assert meta["source_url"].startswith("https://"), f
        assert meta["attachment_sha256"], f
        assert meta["year"] == int(f.parent.name), f
        for subj, blk in doc["subjects"].items():
            # 双档位省用 物理类/历史类；3+3 省用 综合/选考X；其余（如 3+1+2）同前
            assert subj in (
                "物理类", "历史类", "综合",
                "选考物理", "选考化学", "选考生物",
                "选考思想政治", "选考历史", "选考地理",
            ), f
            rows = blk["rows"]
            assert len(rows) > 100, f  # 一分一段表至少几百行
            width = len(rows[0])
            assert width in (3, 5), f
            prev = None
            for r in rows:
                assert len(r) == width, f
                score, sb, cb = r[0], r[1], r[2]
                sz, cz = (r[3], r[4]) if width == 5 else (sb, cb)
                if prev is None:
                    # 顶部分数桶可被截断（「X 分及以上共 N 人」），只要求 累计 >= 本段
                    assert cb >= sb and cz >= sz, f
                else:
                    assert score < prev[0], f
                    assert cb == prev[2] + sb, f
                    assert cz == (prev[4] if width == 5 else prev[2]) + sz, f
                prev = (score, sb, cb, sz, cz)


# ---------------------------------------------------------------------------
# 2. 行重建纯函数
# ---------------------------------------------------------------------------
def test_rows_from_lines_layouts_and_noise():
    # 版式 A（2025 物理）：列在 x≈68/191/283/375/476
    la = [
        (68.5, 100.0, "697（含以上）"), (191.1, 100.0, "19"), (283.4, 100.0, "19"),
        (375.7, 100.0, "19"), (476.6, 100.0, "19"),
        (96.2, 87.0, "696"), (191.1, 87.0, "13"), (283.4, 87.0, "32"),
        (375.7, 87.0, "13"), (476.6, 87.0, "32"),
    ]
    # 版式 B（2025 历史）：整体左移 ~57pt（y 错开，避免与版式 A 撞成一行）
    lb = [
        (120.7, 60.0, "672（含以上）"), (217.9, 60.0, "19"), (292.4, 60.0, "19"),
        (367.9, 60.0, "19"), (443.4, 60.0, "19"),
    ]
    # 噪声：标题/表头/页脚/孤立行必须被剔除
    noise = [
        (136.9, 130.0, "广东省2025年高考普通类（历史）分数段统计表"),
        (129.6, 122.0, "文化总分"), (186.1, 121.0, "分数段人数（含本"), (204.1, 119.0, "科加分）"),
        (247.8, 115.0, "本科"), (397.8, 115.0, "专科"),
        (60.0, 90.0, "第 1 页，共 12页"), (50.0, 88.0, "广东省教育考试院"),
        (300.0, 50.0, "孤行"),
    ]
    rows = _rows_from_lines(la + lb + noise)
    assert rows == [
        ["697（含以上）", 19, 19, 19, 19],
        ["696", 13, 32, 13, 32],
        ["672（含以上）", 19, 19, 19, 19],
    ]


def test_rows_from_lines_wide_numbers_keep_columns():
    # 5 位数累计（x 左移）不能把相邻列并进来
    lines = []
    y = 100.0
    for i, (s, sb, cb, sz, cz) in enumerate([(700, 6, 6, 6, 6), (699, 3, 9, 3, 9), (698, 1, 10, 1, 10)]):
        yy = y - i * 13
        lines += [(96.0, yy, str(s)), (211.0, yy, str(sb)), (270.5, yy, str(cb)),
                  (355.0, yy, str(sz)), (425.0, yy, str(cz))]
    rows = _rows_from_lines(lines)
    assert [r[0] for r in rows] == ["700", "699", "698"]
    assert rows[2] == ["698", 1, 10, 1, 10]


# ---------------------------------------------------------------------------
# 3. 校验器
# ---------------------------------------------------------------------------
def test_validate_rows_accepts_good_and_rejects_bad():
    good = [[697, 19, 19, 19, 19], [696, 13, 32, 13, 32], [695, 7, 39, 7, 39]]
    validate_rows(good)
    for bad in (
        [[697, 19, 10, 19, 19]],                      # 首行累计 < 本段（负数前缀，不可能）
        [[697, 19, 19, 19, 19], [696, 13, 31, 13, 32]],  # 本科累计断裂
        [[697, 19, 19, 19, 19], [697, 0, 19, 0, 19]],    # 分数非严格降序
        [[697, -1, -1, 19, 19]],                      # 负数
    ):
        try:
            validate_rows(bad)
        except ValueError:
            continue
        raise AssertionError(f"坏数据未被拒收: {bad}")


# ---------------------------------------------------------------------------
# 4. 服务层
# ---------------------------------------------------------------------------
def test_years_overview_and_doc():
    ys = RT.years()
    assert ys, "应有已落盘年份"
    assert all(set(y) == {"year", "provinces"} for y in ys)
    years_desc = [y["year"] for y in ys]
    assert years_desc == sorted(years_desc, reverse=True)
    y0 = ys[0]
    p0 = y0["provinces"][0]
    assert set(p0) == {"province", "subjects", "rows", "source_url"}
    doc = RT.doc(y0["year"], p0["province"])
    assert doc and doc["meta"]["province"] == p0["province"]
    assert RT.doc(1999, "广东") is None


def test_lookup_exact_and_lower_bound():
    ys = RT.years()
    y0, p0 = ys[0]["year"], ys[0]["provinces"][0]["province"]
    doc = RT.doc(y0, p0)
    subj = sorted(doc["subjects"])[0]
    rows = doc["subjects"][subj]["rows"]
    # 精确命中
    r = RT.lookup(y0, p0, subj, rows[5][0])
    assert r["exact"] is True and r["matched_score"] == rows[5][0]
    assert r["cum_ben"] == rows[5][2]
    # 3 列=单档位（cum_zhuan 镜像 cum）；5 列=双档位（各有独立值）
    if len(rows[5]) > 4:
        assert r["cum_zhuan"] == rows[5][4] and r["rank_track"] == "dual"
    else:
        assert r["cum_zhuan"] == rows[5][2] and r["rank_track"] == "single"
    # 非精确：分数高于表内最高分（如含以上档再+1）-> 取最高分行作位次上界
    r2 = RT.lookup(y0, p0, subj, rows[0][0] + 1)
    assert r2["exact"] is False and r2["matched_score"] == rows[0][0]
    # 超界
    assert RT.lookup(y0, p0, subj, 0) is None
    assert RT.lookup(y0, p0, "不存在", 600) is None


# ---------------------------------------------------------------------------
# 5. 落库幂等 + 溯源硬规矩
# ---------------------------------------------------------------------------
def _run_import(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, XUEFENG_DB_PATH=str(db), TMPDIR="/tmp")
    return subprocess.run(
        [sys.executable, str(_BACKEND / "scripts" / "import_rank_tables.py"), *args],
        env=env, cwd=str(_BACKEND), capture_output=True, text=True, timeout=300,
    )


def _count_segments(db: Path) -> int:
    import sqlite3

    con = sqlite3.connect(str(db))
    try:
        return con.execute("SELECT COUNT(*) FROM rank_segments").fetchone()[0]
    finally:
        con.close()


def test_import_idempotent_and_replaces_group():
    docs = _landed_docs()
    assert docs, "需要至少一份已落盘 JSON"
    with tempfile.TemporaryDirectory(dir=str(_BACKEND / "tests" / ".bk_tmp")) as td:
        db = Path(td) / "rank.db"
        r1 = _run_import(db)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        n1 = _count_segments(db)
        assert n1 > 1000
        # 重复导入幂等
        r2 = _run_import(db)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert _count_segments(db) == n1


def test_import_rejects_missing_source_url():
    docs = _landed_docs()
    f, doc = docs[0]
    bad = json.loads(json.dumps(doc))
    bad["meta"].pop("source_url", None)
    with tempfile.TemporaryDirectory(dir=str(_BACKEND / "tests" / ".bk_tmp")) as td:
        bad_path = Path(td) / f"{bad['meta']['province']}.json"
        bad_path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        imp = importlib.import_module("import_rank_tables")
        try:
            imp.import_file(bad_path)
        except ValueError as e:
            assert "source_url" in str(e)
        else:
            raise AssertionError("缺 source_url 的数据未被拒收")


# ---------------------------------------------------------------------------
# 6. API
# ---------------------------------------------------------------------------
def test_api_rank_tables_endpoints():
    ys = RT.years()
    y0 = ys[0]["year"]
    p0 = ys[0]["provinces"][0]["province"]

    r = _client().get("/api/rank-tables")
    assert r.status_code == 200
    assert r.json()["years"][0]["year"] == y0

    r = _client().get(f"/api/rank-tables/{y0}/{p0}")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["source_url"].startswith("https://")

    doc = RT.doc(y0, p0)
    subj = sorted(doc["subjects"])[0]
    score = doc["subjects"][subj]["rows"][10][0]
    r = _client().get(
        f"/api/rank-tables/lookup?year={y0}&province={p0}&subject={subj}&score={score}")
    assert r.status_code == 200
    assert r.json()["exact"] is True

    r = _client().get("/api/rank-tables/1999/广东")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 7. 单档位（3 列）与顶部截断桶：跨省口径差异
# ---------------------------------------------------------------------------
def test_validate_rows_single_track_and_truncated_top():
    # 单档位：cum = prev_cum + seg
    validate_rows([[692, 7, 54], [691, 14, 68], [690, 12, 80]])
    # 顶部截断桶（692 及以上 54 人，而 692 只有 7 人）必须被接受
    validate_rows([[692, 7, 54], [691, 14, 68]])
    # 首行 累计 < 本段 是错的（不可能有负数前缀）
    with pytest.raises(ValueError):
        validate_rows([[692, 54, 7]])
    # 断链必须拦
    with pytest.raises(ValueError):
        validate_rows([[692, 7, 54], [691, 14, 69]])
    # 非降序必须拦
    with pytest.raises(ValueError):
        validate_rows([[691, 7, 7], [692, 14, 21]])
    # 不支持的行宽必须拦（防止上游把 4 列脏数据塞进来）
    with pytest.raises(ValueError):
        validate_rows([[692, 7, 54, 7]])


def test_lookup_single_track_marks_rank_track(monkeypatch):
    """3 列文档：cum_zhuan 取 cum（单档省只公布一套累计），并标 rank_track=single。"""
    # 沙箱 shim 对已存在目录的 mkdir(exist_ok=True) 仍会抛 EEXIST，故先判存在
    base = _BACKEND / "tests" / ".bk_tmp"
    if not base.is_dir():
        base.mkdir(parents=True)
    tmpdir = Path(tempfile.mkdtemp(dir=str(base)))
    (tmpdir / "2099").mkdir(parents=True)
    doc = {
        "meta": {"year": 2099, "province": "测试省", "data_source": "official",
                 "source_url": "https://example.edu.cn/notice.html"},
        # 故意留出 699 的缺口，用于验证「非精确命中取位次上界」
        "subjects": {"综合": {"rows": [[700, 2, 5], [698, 4, 12], [697, 3, 15]]}},
    }
    (tmpdir / "2099" / "测试省.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(RT, "DATA", tmpdir)
    RT._load.cache_clear()
    try:
        got = RT.lookup(2099, "测试省", "综合", 700)
        assert got["exact"] is True and got["cum_ben"] == 5
        assert got["cum_zhuan"] == 5 and got["rank_track"] == "single"
        # 分数不在表中 -> 取不高于该分的最近行（位次上界），标 exact=False
        got2 = RT.lookup(2099, "测试省", "综合", 699)
        assert got2["exact"] is False and got2["matched_score"] == 698
        assert got2["cum_ben"] == 12
    finally:
        RT._load.cache_clear()
