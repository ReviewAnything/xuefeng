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
        # 附件型（PDF/XLS）记 attachment_sha256；HTML 直出型记 source_sha256
        assert meta.get("attachment_sha256") or meta.get("source_sha256"), f
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


# ---------------------------------------------------------------------------
# 8. 省级注册表 / 按省同步（S11）：一键同步的工具面
# ---------------------------------------------------------------------------
def test_province_registry_covers_31_and_marks_blocked():
    from rank_sync import ALL_PROVINCES, BLOCKED, overview

    ov = overview()
    assert ov["total_provinces"] == 31 == len(ALL_PROVINCES)
    assert len(ov["provinces"]) == 31
    assert sum(ov["counts"].values()) == 31
    status = {p["province"]: p["status"] for p in ov["provinces"]}
    for prov in ("广东", "山东", "浙江", "湖北", "湖南"):
        assert status[prov] == "ready", prov
    for prov in ("四川", "河北", "河南"):
        assert status[prov] == "blocked", prov
        assert BLOCKED[prov], "受阻必须写明原因，不能只标状态"


def test_overview_reports_disk_coverage_and_gaps():
    from rank_sync import overview

    rows = {r["province"]: r for r in overview()["provinces"]}
    gd = rows["广东"]
    assert 2025 in gd["covered_years"]
    assert gd["covered"]["2025"]["rows"] > 500
    # 广东 2023 是扫描件：必须显式登记为 known_gap，而不是静默缺失
    assert 2023 in gd["known_gaps"]
    assert "扫描件" in gd["known_gaps"][2023]


def test_sync_blocked_or_unknown_province_returns_reason():
    from rank_sync import sync

    rep = sync("四川")
    assert rep["ok"] is False and "图片" in rep["error"]
    rep2 = sync("火星省")
    assert rep2["ok"] is False and rep2["error"]


def test_parse_html_table_splits_below_bucket():
    from rank_sync import common as RSC

    html = """<table>
      <tr><td>档分</td><td>本段人数</td><td>累计人数</td></tr>
      <tr><td>101</td><td>2</td><td>10</td></tr>
      <tr><td>100</td><td>4</td><td>14</td></tr>
      <tr><td>100</td><td>1369</td><td>1383</td></tr>
    </table>"""
    rows, note, below = RSC.parse_html_table(html)
    assert rows == [[101, 2, 10], [100, 4, 14]]
    assert below == {"score_below": 100, "seg": 1369, "cum": 1383}
    validate_rows(rows)
    # 首行 累计(10) > 本段(2) -> 顶部有截断桶（101 之上还有 8 人），必须标注
    assert note == "101↑"


def test_block_header_pattern_covers_zhejiang_and_hubei_layouts():
    from rank_sync import common as RSC

    # 浙江：三个「总分」格；湖北：一整行「分数 人数 累计人数」
    assert RSC.BLOCK_HEADER_PAT.match("总分")
    assert RSC.BLOCK_HEADER_PAT.match("分数 人数 累计人数")
    assert RSC.BLOCK_HEADER_PAT.match("档分")
    assert not RSC.BLOCK_HEADER_PAT.match("693")


def test_admin_rank_sync_endpoint_requires_auth_and_delegates(monkeypatch):
    from tests.helpers import ready_headers

    client = _client()
    assert client.get("/api/admin/rank-tables/provinces").status_code in (401, 403)

    headers = ready_headers(client)
    ok = client.get("/api/admin/rank-tables/provinces", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["total_provinces"] == 31

    import rank_sync

    seen = {}

    def fake_sync(province, years=None, dry_run=False, out_dir=None):
        seen.update(province=province, years=years, dry_run=dry_run)
        return {"ok": True, "province": province, "dry_run": dry_run,
                "years": [{"year": 2025, "ok": True, "rows": 3, "subjects": {"综合": 3}}],
                "saved": 1, "failed": 0}

    monkeypatch.setattr(rank_sync, "sync", fake_sync)
    r = client.post("/api/admin/rank-tables/sync", headers=headers,
                    json={"province": "浙江", "dry_run": True, "write_db": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["db"] == []
    assert seen == {"province": "浙江", "years": None, "dry_run": True}


def test_admin_rank_sync_blocked_province_is_400():
    from tests.helpers import ready_headers

    client = _client()
    headers = ready_headers(client)
    r = client.post("/api/admin/rank-tables/sync", headers=headers,
                    json={"province": "四川", "dry_run": True, "write_db": False})
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# 9. 双轨表（湖南 2022–2024）：主轨取含全国性加分，地方性加分单列
# ---------------------------------------------------------------------------
def test_parse_html_table_dual_track_keeps_both_tracks():
    from rank_sync import common as RSC

    html = """<table>
      <tr><td>档分</td><td>本段人数</td><td>累计人数</td><td>本段人数</td><td>累计人数</td></tr>
      <tr><td>(含全国性加分)</td><td></td><td></td><td>(含全国性和地方性加分)</td><td></td></tr>
      <tr><td>692</td><td>8</td><td>57</td><td>8</td><td>59</td></tr>
      <tr><td>691</td><td>13</td><td>70</td><td>11</td><td>70</td></tr>
      <tr><td>690</td><td>4</td><td>74</td><td>4</td><td>74</td></tr>
      <tr><td>100以下</td><td>1226</td><td>1300</td><td>1226</td><td>1302</td></tr>
    </table>"""
    rows, note, below, alt = RSC.parse_html_table(html, tracks=True)
    # 主轨 = 含全国性加分（投档位次口径），不是地方性加分轨
    assert rows == [[692, 8, 57], [691, 13, 70], [690, 4, 74]]
    assert alt == {"label": "含全国性和地方性加分",
                   "rows": [[692, 8, 59], [691, 11, 70], [690, 4, 74]]}
    assert below == {"score_below": 100, "seg": 1226, "cum": 1300}
    validate_rows(rows)
    validate_rows(alt["rows"])  # 副轨也必须自洽，否则整份都不可信
    # 主轨顶部截断桶（57 > 8）要给出备注，副轨不覆盖
    assert note == "692↑"


def test_parse_html_table_single_track_has_no_alt():
    from rank_sync import common as RSC

    html = ("<table><tr><td>档分</td><td>本段人数</td><td>累计人数</td></tr>"
            "<tr><td>690</td><td>3</td><td>3</td></tr>"
            "<tr><td>689</td><td>5</td><td>8</td></tr></table>")
    rows, note, below, alt = RSC.parse_html_table(html, tracks=True)
    assert alt is None and below is None
    assert note == ""  # 首行 累计==本段（顶分单独一行）时不给顶部备注
    assert rows == [[690, 3, 3], [689, 5, 8]]


def test_fetch_retries_through_error_page(monkeypatch):
    """省站限流时会回「HTTP 200 + 555 字节 404 页」，不能当正文。"""
    from rank_sync import common as RSC

    class _Resp:
        def __init__(self, body, code=200):
            self.content = body
            self.status_code = code

        def raise_for_status(self):
            if self.status_code >= 400:
                import requests
                raise requests.exceptions.HTTPError("boom")

    bad = b"<html><head><title>404 Not Found</title></head><body>nginx/1.18.0</body></html>"
    good = b"<html><body>" + b"x" * 5000 + b"</body></html>"
    seq = [_Resp(bad), _Resp(bad), _Resp(good)]

    def fake_get(url, headers=None, timeout=None):
        return seq.pop(0)

    monkeypatch.setattr(RSC.requests, "get", fake_get)
    monkeypatch.setattr(RSC.time, "sleep", lambda *_: None)
    assert RSC.http_get("https://example.edu.cn/x", retries=4) == good


# ---------------------------------------------------------------------------
# 10. 陕西三列表：截断桶人数留空 / 分数不连续 / 两位数低分 / 丢行必须报错
# ---------------------------------------------------------------------------
def _sx_parse(html):
    from rank_sync.provinces import shaanxi as SX
    return SX.parse_table(html)


def test_shaanxi_table_handles_truncated_top_and_below_bucket():
    # 2023 式：顶部「710分以上」人数留空；表尾「101分以下及缺考」
    html = """<table>
      <tr><td>分数</td><td>人数</td><td>总人数</td></tr>
      <tr><td>710分以上</td><td></td><td>12</td></tr>
      <tr><td>709</td><td>1</td><td>13</td></tr>
      <tr><td>707</td><td>2</td><td>15</td></tr>
      <tr><td>101分以下及缺考</td><td>50</td><td>65</td></tr>
    </table>"""
    rows, note, below = _sx_parse(html)
    # 709 与 707 之间缺 708（0 人的分整行不印），不能因此报错
    assert rows == [[710, 12, 12], [709, 1, 13], [707, 2, 15]]
    assert note == "710↑"
    assert below == {"score_below": 101, "seg": 50, "cum": 65}
    validate_rows(rows)


def test_shaanxi_table_keeps_two_digit_low_scores():
    # 2022 式：低分段是两位数，且表尾是「50分以下或缺考」
    html = """<table>
      <tr><td>699分以上</td><td></td><td>9</td></tr>
      <tr><td>698</td><td>6</td><td>15</td></tr>
      <tr><td>52</td><td>1</td><td>164940</td></tr>
      <tr><td>50分以下或缺考</td><td>1516</td><td>166456</td></tr>
    </table>"""
    rows, note, below = _sx_parse(html)
    assert rows[0] == [699, 9, 9] and note == "699↑"
    assert rows[-1] == [52, 1, 164940], "两位数的低分档不能被丢掉"
    assert below["score_below"] == 50 and below["cum"] == 166456


def test_shaanxi_table_refuses_to_drop_unparsed_rows():
    """看起来像数据却解析不了 -> 整份拒收（曾静默丢掉 50–99 分整段）。"""
    html = """<table>
      <tr><td>709及以上</td><td>13</td><td>13</td></tr>
      <tr><td>708</td><td>3</td><td>16</td></tr>
      <tr><td>708(补)</td><td>3</td><td>19</td></tr>
    </table>"""
    with pytest.raises(ValueError, match="疑似数据未解析"):
        _sx_parse(html)


def test_shaanxi_subject_aliases_map_wenli_to_physics_history():
    """2022–2024 是文理分科：理工->物理类、文史->历史类，且原始表头必须留痕。"""
    from rank_sync.provinces import shaanxi as SX

    assert SX.LABELS[2024] == {"物理类": "理工", "历史类": "文史"}
    assert SX.LABELS[2025] == {"物理类": "物理", "历史类": "历史"}
    assert set(SX.NOTICES) == {2022, 2023, 2024, 2025, 2026}
    for year, pages in SX.NOTICES.items():
        assert set(pages) == {"物理类", "历史类"}, year


# ---------------------------------------------------------------------------
# 10. 安徽：合并行拆分 / 行聚簇 / 末行桶与截断说明 / 文理分科别名
# ---------------------------------------------------------------------------
def test_anhui_split_pattern_takes_shortest_cumulative():
    """2023 实测：'144375200 以下' 必须拆成 144375 + '200 以下'。

    贪婪匹配会错拆成 '14437520' + '0 以下'（累计少一位、分数变成 0），
    且累计链仍可能自洽——必须靠懒惰匹配 + 分数首位非零防住。
    """
    from rank_sync.provinces import anhui as AH

    for text, digits, note in (
        ("144375200 以下", "144375", "200 以下"),
        ("292967200 以下", "292967", "200 以下"),
        ("137403 200以下", "137403", "200以下"),
        ("162638 200及以下", "162638", "200及以下"),
    ):
        m = AH.NOTE_SPLIT_PAT.match(text)
        assert m, text
        assert m.group(1) == digits and m.group(2) == note, text


def test_anhui_clean_lines_splits_merged_cell_and_drops_footer():
    """「上一组累计 + 下一组分数格」黏连行拆成两个单元格，页脚被剔除。"""
    from rank_sync.provinces import anhui as AH

    lines = [
        (62.3, 82.3, 500.0, "分数"),                      # 表头（不参与）
        (51.1, 96.0, 490.0, "637及以上"),
        (136.3, 146.5, 490.0, "22"),
        (187.0, 197.0, 490.0, "22"),
        (166.7, 246.0, 478.0, "162638 200及以下"),        # 黏连行
        (271.1, 296.1, 478.3, "17015"),
        (315.7, 345.8, 478.0, "182811"),
        (384.7, 456.2, 20.0, "第 1 页，共 6 页"),
    ]
    cells = AH._clean_lines(lines)
    texts = [t for _x0, _x1, _y, t in cells]
    assert "162638" in texts and "200及以下" in texts, texts
    assert not any("第" in t for t in texts), texts
    # 拆出的数字格 x1 按数字宽度重建，必须仍落在累计列（197.0）上
    cum_cell = next(c for c in cells if c[3] == "162638")
    assert abs(cum_cell[1] - 197.0) <= 1.0
    # 注释格保留整行右边界（246.0，即下一组分数列），聚类只认 x1
    note_cell = next(c for c in cells if c[3] == "200及以下")
    assert abs(note_cell[1] - 246.0) <= 0.01


def test_anhui_group_rows_keeps_cells_within_tolerance():
    """同一行单元格 y 可差 0.3pt（124.4 vs 124.7），不能被 round(y/3) 劈开。"""
    from rank_sync.provinces import anhui as AH

    cells = [
        (80.9, 95.9, 124.4, "237"),
        (131.3, 146.4, 124.4, "108"),
        (166.7, 196.7, 124.4, "162638"),
        (271.1, 296.1, 124.7, "17015"),
        (315.7, 345.8, 124.4, "182811"),
        (80.9, 95.9, 112.0, "236"),
    ]
    rows = AH._group_rows(cells)
    assert len(rows) == 2
    assert len(rows[0]) == 5 and len(rows[1]) == 1


def test_anhui_parse_page_below_bucket_with_numbers():
    """2022 式末行：'200及以下' 落在分数列且带人数/累计 -> below_bucket。"""
    from rank_sync.provinces import anhui as AH

    cells = [
        # 组0（列右边界 96/146/197）
        (81.0, 96.0, 200.0, "300"), (131.0, 146.0, 200.0, "10"), (167.0, 197.0, 200.0, "10"),
        (81.0, 96.0, 188.0, "299"), (131.0, 146.0, 188.0, "8"), (167.0, 197.0, 188.0, "18"),
        (81.0, 96.0, 176.0, "298"), (131.0, 146.0, 176.0, "7"), (167.0, 197.0, 176.0, "25"),
        # 组1（列右边界 247/297/347），末行是「200及以下」桶（接得上累计链）
        (232.0, 247.0, 200.0, "200"), (282.0, 297.0, 200.0, "5"), (317.0, 347.0, 200.0, "30"),
        (232.0, 247.0, 188.0, "199"), (282.0, 297.0, 188.0, "6"), (317.0, 347.0, 188.0, "36"),
        (232.0, 247.0, 176.0, "200及以下"), (282.0, 297.0, 176.0, "9"),
        (317.0, 347.0, 176.0, "45"),
    ]
    rows, omits, belows, dropped = AH._parse_page(cells)
    assert dropped == []
    assert rows == [[300, 10, 10], [299, 8, 18], [298, 7, 25], [200, 5, 30], [199, 6, 36]]
    assert belows == [{"score_below": 200, "seg": 9, "cum": 45}]
    assert omits == []
    validate_rows(rows)


def test_anhui_parse_page_floating_note_is_omitted_not_dropped():
    """2025 式：落在任何列簇之外的「200以下」是表尾游离注释 -> omitted。"""
    from rank_sync.provinces import anhui as AH

    cells = [
        (81.0, 96.0, 200.0, "300"), (131.0, 146.0, 200.0, "10"), (167.0, 197.0, 200.0, "10"),
        (81.0, 96.0, 188.0, "299"), (131.0, 146.0, 188.0, "8"), (167.0, 197.0, 188.0, "18"),
        (81.0, 96.0, 176.0, "298"), (131.0, 146.0, 176.0, "7"), (167.0, 197.0, 176.0, "25"),
        (211.0, 224.0, 176.0, "200以下"),   # 游离在累计列右侧 13pt，不属于任何列
    ]
    rows, omits, belows, dropped = AH._parse_page(cells)
    assert rows == [[300, 10, 10], [299, 8, 18], [298, 7, 25]]
    assert omits == [{"score_below": 200, "omitted": True}]
    assert belows == [] and dropped == []


def test_anhui_parse_page_refuses_unparsable_cells():
    """落不进任何列簇、又不是截断注释的文本 -> 整份拒收（不允许静默丢行）。"""
    from rank_sync.provinces import anhui as AH

    cells = [
        (81.0, 96.0, 200.0, "300"), (131.0, 146.0, 200.0, "10"), (167.0, 197.0, 200.0, "10"),
        (211.0, 224.0, 188.0, "缺考"),
    ]
    _rows, _omits, _belows, dropped = AH._parse_page(cells)
    assert dropped, "无法归列的文本必须进 dropped"


def test_anhui_landed_years_have_year_specific_tail_semantics():
    """2022 末行桶带数字；2023 起官方改印「200以下略」只留标记。"""
    from rank_sync.provinces import anhui as AH

    assert set(AH.PDFS) == {2022, 2023, 2024, 2025, 2026}
    for year in (2022, 2023, 2024, 2025, 2026):
        f = _BACKEND / "data" / "rank_tables" / str(year) / "安徽.json"
        doc = json.loads(f.read_text(encoding="utf-8"))
        for subj, blk in doc["subjects"].items():
            if year == 2022:
                assert blk["below_bucket"]["score_below"] == 200, (year, subj)
                assert blk["below_bucket"]["cum"] > blk["rows"][-1][2], (year, subj)
            else:
                assert "below_bucket" not in blk, (year, subj)
                assert blk["omitted_below"] == {"score_below": 200, "omitted": True}


def test_anhui_subject_aliases_map_wenli_years():
    """2022/2023 官方表头写「文史/理工」，落盘必须留痕且口径标文理分科。"""
    from rank_sync.provinces import anhui as AH

    assert AH.SUBJECT_OF_LABEL["文史"] == "历史类"
    assert AH.SUBJECT_OF_LABEL["理工"] == "物理类"
    doc = json.loads((_BACKEND / "data" / "rank_tables" / "2022" / "安徽.json")
                     .read_text(encoding="utf-8"))
    assert doc["meta"]["subject_scheme"] == "文理分科"
    assert doc["meta"]["subject_aliases"] == {"历史类": "文史", "物理类": "理工"}
    doc = json.loads((_BACKEND / "data" / "rank_tables" / "2025" / "安徽.json")
                     .read_text(encoding="utf-8"))
    assert doc["meta"]["subject_scheme"] == "3+1+2"
    assert "subject_aliases" not in doc["meta"]


# ---------------------------------------------------------------------------
# 11. 重庆：顶部只印人数的截断桶 / 零人数分数段缺口 / 三年三种索引目录
# ---------------------------------------------------------------------------
def _cq_table(body: str) -> str:
    return ("<html><body><table>"
            "<tr><td>分数段</td><td>人数</td><td>累计人数</td></tr>"
            + body + "</table></body></html>")


def test_chongqing_top_bucket_prints_only_headcount():
    """顶部「663及以上」只印人数：该桶人数即累计，且要打 top_note。"""
    from rank_sync.provinces import chongqing as CQ

    html = _cq_table(
        "<tr><td>663及以上</td><td>60</td></tr>"
        "<tr><td>662</td><td>8</td><td>68</td></tr>"
        "<tr><td>661</td><td>10</td><td>78</td></tr>")
    rows, top_note, below, dropped = CQ.parse_table(html)
    assert rows == [[663, 60, 60], [662, 8, 68], [661, 10, 78]]
    assert top_note == "663↑"
    assert below is None and dropped == []
    validate_rows(rows)


def test_chongqing_zero_count_gaps_are_recorded_not_dropped():
    """官方不印「本段人数 0」的分数段（2026 物理缺 188），累计链仍自洽。

    这类缺口必须显式记录：按「逐分连续」校验会把官方口径判成漏行。
    """
    from rank_sync.provinces import chongqing as CQ

    html = _cq_table(
        "<tr><td>190</td><td>7</td><td>135591</td></tr>"
        "<tr><td>189</td><td>1</td><td>135592</td></tr>"
        "<tr><td>187</td><td>2</td><td>135594</td></tr>")
    rows, _note, _below, _dropped = CQ.parse_table(html)
    validate_rows(rows)
    assert CQ._gaps(rows) == [188]


def test_chongqing_below_bucket_and_title_rows():
    """「N 分以下」桶单列返回；WPS 导出页的标题行与空行不算未解析。"""
    from rank_sync.provinces import chongqing as CQ

    html = (_cq_table(
        "<tr><td>182</td><td>3</td><td>132322</td></tr>"
        "<tr><td>180</td><td>3</td><td>132325</td></tr>"
        "<tr><td>180分以下</td><td>9</td><td>132334</td></tr>")
        .replace("<tr><td>分数段</td><td>人数</td><td>累计人数</td></tr>",
                 "<tr><td>2022年物理类含加分一分段表[志愿填报]</td></tr>"
                 "<tr><td>分数段</td><td>人数</td><td>累计人数</td></tr>"
                 "<tr><td></td></tr>"))
    rows, _note, below, dropped = CQ.parse_table(html)
    assert rows == [[182, 3, 132322], [180, 3, 132325]]
    assert below == {"score_below": 180, "seg": 9, "cum": 132334}
    assert dropped == []


def test_chongqing_refuses_unparsable_row():
    """落不进任何一种行型的文本 -> 交给调用方整份拒收。"""
    from rank_sync.provinces import chongqing as CQ

    html = _cq_table("<tr><td>缺考</td><td>3</td><td>9</td></tr>")
    rows, _note, _below, dropped = CQ.parse_table(html)
    assert rows == [] and dropped


def test_chongqing_landed_five_years_with_year_specific_dirs():
    """2022–2024 在官方「往年」归档页，2025 在 pg 目录，2026 起在 ptgk 目录。"""
    from rank_sync.provinces import chongqing as CQ

    assert set(CQ.PAGES) == {2022, 2023, 2024, 2025, 2026}
    assert "/hist/www2022/" in CQ.PAGES[2022]
    assert "/2025/pg/yfd/fdb.htm" in CQ.PAGES[2025]
    assert "/2026/ptgk/yfd/fdb.htm" in CQ.PAGES[2026]
    for year in (2022, 2023, 2024, 2025, 2026):
        doc = json.loads((_BACKEND / "data" / "rank_tables" / str(year) / "重庆.json")
                         .read_text(encoding="utf-8"))
        meta = doc["meta"]
        assert meta["subject_scheme"] == "3+1+2", year
        assert meta["data_source"] == "official"
        assert meta["source_url"] == CQ.PAGES[year]
        assert set(doc["subjects"]) == {"物理类", "历史类"}
        for subj, blk in doc["subjects"].items():
            rows = blk["rows"]
            validate_rows(rows)
            assert len(rows) > 400, (year, subj)
            # 官方表底：常规止于 180；2023 物理当年只印到 182
            expect_floor = 182 if (year, subj) == (2023, "物理类") else 180
            assert rows[-1][0] == expect_floor, (year, subj, rows[-1][0])
            assert meta["score_floor"][subj] == expect_floor
            # 缺口 = 官方未印的分数段，必须是「累计链仍自洽」的真缺口
            gaps = blk.get("omitted_scores") or []
            assert all(rows[0][0] >= g > rows[-1][0] for g in gaps), (year, subj, gaps)


def test_chongqing_landed_anchors_match_official_release():
    """2025/2026 与官方通稿逐项对齐（含加分口径、本科线处的累计人数）。"""
    def load(year):
        return json.loads((_BACKEND / "data" / "rank_tables" / str(year) / "重庆.json")
                          .read_text(encoding="utf-8"))

    d25 = load(2025)["subjects"]
    hist25 = {r[0]: r for r in d25["历史类"]["rows"]}
    phys25 = {r[0]: r for r in d25["物理类"]["rows"]}
    assert hist25[650][2] == 80 and hist25[600][2] == 1576
    assert hist25[438][2] == 35253 and hist25[515][1] == 248   # 本科线 / 压线人数
    assert phys25[680][2] == 176 and phys25[600][2] == 11716
    assert phys25[425][2] == 103219 and phys25[498][1] == 648

    d26 = load(2026)["subjects"]
    hist26 = {r[0]: r for r in d26["历史类"]["rows"]}
    phys26 = {r[0]: r for r in d26["物理类"]["rows"]}
    assert hist26[660][2] == 89 and hist26[600][2] == 2120
    assert hist26[415][2] == 38962 and hist26[500][2] == 17442
    assert phys26[680][2] == 228 and phys26[600][2] == 12895
    assert phys26[406][2] == 107000 and phys26[496][1] == 523
    assert d26["物理类"]["omitted_scores"] == [188]
