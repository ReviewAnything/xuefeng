"""rank_sync 新增适配器（山西官方 / 河南第三方文本）离线不变量测试。

不依赖网络：用合成 HTML 验证
1. 山西双栏表解析（_parse_double_table）——同一分布拆左右两栏印刷，重排后必须
   分数严格降序、累计=前项+本段（common.validate_rows 通过）；
2. 河南第三方文本解析（parse_html_table）——单栏 <tr><td> 三列，build 出的 doc
   结构正确、data_source=third_party_text、两科均通过强校验。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from rank_sync.common import validate_rows  # noqa: E402
import rank_sync.provinces.shanxi as shanxi  # noqa: E402
import rank_sync.provinces.henan as henan  # noqa: E402


# 山西双栏合成：左栏 650/649/648，右栏 647/646/645（跨栏连续，累计链不断）
_SHANXI_HTML = """
<table style="WIDTH: 21cm">
<tr><td>分数</td><td>本分人数</td><td>累计人数</td><td>分数</td><td>本分人数</td><td>累计人数</td></tr>
<tr><td>650及以上</td><td>5</td><td>5</td><td>647</td><td>4</td><td>14</td></tr>
<tr><td>649</td><td>3</td><td>8</td><td>646</td><td>1</td><td>15</td></tr>
<tr><td>648</td><td>2</td><td>10</td><td>645</td><td>6</td><td>21</td></tr>
</table>
"""

# 河南单栏合成：分数/人数/累计
_HENAN_HTML = """
<table>
<tr><td>分数</td><td>人数</td><td>累计人数</td></tr>
<tr><td>700</td><td>2</td><td>2</td></tr>
<tr><td>699</td><td>3</td><td>5</td></tr>
<tr><td>698</td><td>4</td><td>9</td></tr>
</table>
"""


def test_shanxi_double_table_parse():
    rows = shanxi._parse_double_table(_SHANXI_HTML)
    assert rows == [[650, 5, 5], [649, 3, 8], [648, 2, 10],
                    [647, 4, 14], [646, 1, 15], [645, 6, 21]], rows
    validate_rows(rows)  # 不抛异常即通过


def test_shanxi_registry_and_years():
    import rank_sync.provinces as P
    assert P.REGISTRY["山西"] is shanxi
    assert P.REGISTRY["河南"] is henan
    assert shanxi.PROVINCE == "山西" and shanxi.STATUS == "ready"
    # 注册的年份逐年可用
    for y in shanxi.PAGES:
        assert shanxi.PAGES[y], y


def test_henan_parse_third_party_text():
    # 取数在 common.doc_from_html_pages 里，补丁要打在 common 上
    with mock.patch("rank_sync.common.http_get_html", return_value=_HENAN_HTML):
        doc = henan.parse(2024)
    assert doc["meta"]["data_source"] == "third_party_text"
    assert doc["meta"]["province"] == "河南"
    assert set(doc["subjects"]) == {"文科", "理科"}
    for subj, blk in doc["subjects"].items():
        assert blk["source_url"].startswith("http")
        validate_rows(blk["rows"])
        assert blk["rows"][0][0] == 700  # 顶分降序首位


def test_henan_registry():
    import rank_sync.provinces as P
    assert P.REGISTRY["河南"] is henan
    assert henan.STATUS == "ready"


# ---------------------------------------------------------------------------
# common.parse_html_table 的两个真实源站坑（福建 / 江苏），回归守护
# ---------------------------------------------------------------------------
# 福建：关键批次线所在行被标注成「520（特招线）」，严格 fullmatch 会整行丢掉
_FUJIAN_HTML = """
<table>
<tr><td>分数</td><td>人数</td><td>累计人数</td></tr>
<tr><td>689-750</td><td>46</td><td>46</td></tr>
<tr><td>522</td><td>10</td><td>56</td></tr>
<tr><td>521</td><td>4</td><td>60</td></tr>
<tr><td>520（特招线）</td><td>6</td><td>66</td></tr>
<tr><td>519</td><td>7</td><td>73</td></tr>
</table>
"""

# 江苏：单元格里混了 &nbsp; 实体（657&nbsp;），isdigit() 会失败
_JIANGSU_HTML = """
<table>
<tr><td>分数</td><td>人数</td><td>累计人数</td></tr>
<tr><td>658-750</td><td>109</td><td>109</td></tr>
<tr><td>657&nbsp;</td><td>16&nbsp;</td><td>125&nbsp;</td></tr>
<tr><td>656&nbsp;</td><td>15&nbsp;</td><td>140&nbsp;</td></tr>
</table>
"""


def test_html_table_annotated_score_rows():
    """「520（特招线）」这类标注行必须取前导整数，丢掉会让累计链断裂。"""
    from rank_sync.common import parse_html_table
    rows, top, _below = parse_html_table(_FUJIAN_HTML)
    assert [r[0] for r in rows] == [522, 521, 520, 519], rows
    validate_rows(rows)                    # 含 520 后累计链连续
    assert top == "522↑"                   # 区间行 689-750 仍按顶部截断桶处理


def test_html_table_nbsp_entities():
    """&nbsp; 是实体不是空白，必须先 unescape，否则整页 0 行。"""
    from rank_sync.common import parse_html_table
    rows, top, _below = parse_html_table(_JIANGSU_HTML)
    assert rows == [[657, 16, 125], [656, 15, 140]], rows
    validate_rows(rows)


# ---------------------------------------------------------------------------
# 9 个第三方文本转录省（四川/河北/江苏/福建/云南/贵州/甘肃/天津/海南）
# ---------------------------------------------------------------------------
NEW_PROVS = {
    "四川": "sichuan", "河北": "hebei", "江苏": "jiangsu", "福建": "fujian",
    "云南": "yunnan", "贵州": "guizhou", "甘肃": "gansu", "天津": "tianjin",
    "海南": "hainan",
}

_SYN_TABLE = """
<table>
<tr><td>分数</td><td>人数</td><td>累计人数</td></tr>
<tr><td>700</td><td>2</td><td>2</td></tr>
<tr><td>699</td><td>3</td><td>5</td></tr>
<tr><td>698</td><td>4</td><td>9</td></tr>
</table>
"""


def test_new_adapters_registered():
    import rank_sync.provinces as P
    for prov, mod_name in NEW_PROVS.items():
        mod = P.REGISTRY.get(prov)
        assert mod is not None, f"{prov} 未注册"
        assert mod.PROVINCE == prov and mod.STATUS == "ready"
        assert mod.SUBJECTS, f"{prov} 缺 SUBJECTS"
        assert mod.PAGES, f"{prov} 缺 PAGES"
        assert mod.__name__.endswith(mod_name)


def test_new_adapters_never_claim_official():
    """治理红线：第三方文本转录绝不能标 official，且每行都要能溯源。"""
    import rank_sync.provinces as P
    for prov in NEW_PROVS:
        mod = P.REGISTRY[prov]
        assert mod.DATA_SOURCE == "third_party_text", prov
        for year, pages in mod.PAGES.items():
            assert isinstance(year, int) and 2020 <= year <= 2030
            for subj, url in pages.items():
                assert url.startswith("https://"), (prov, url)
                assert "eol.cn" in url, (prov, url)   # 溯源域名留痕


def test_new_adapters_known_gaps_declared():
    """解封不等于全覆盖：缺的年份必须显式登记，不能静默变成「该年无数据」。"""
    import rank_sync.provinces as P
    for prov in NEW_PROVS:
        mod = P.REGISTRY[prov]
        declared = set(mod.PAGES) | set(mod.KNOWN_GAPS)
        assert declared, prov
        for year in (2022, 2023, 2024, 2025):
            assert year in declared, f"{prov} {year} 既无 PAGES 也未登记 KNOWN_GAPS"


def test_new_adapters_parse_offline():
    """合成 HTML 跑通 doc 组装：结构、溯源、强校验、data_source 全对。"""
    import rank_sync.provinces as P
    for prov in NEW_PROVS:
        mod = P.REGISTRY[prov]
        for year in mod.PAGES:
            with mock.patch("rank_sync.common.http_get_html", return_value=_SYN_TABLE):
                doc = mod.parse(year)
            assert doc["meta"]["province"] == prov
            assert doc["meta"]["data_source"] == "third_party_text"
            assert set(doc["subjects"]) == set(mod.PAGES[year])
            for subj, blk in doc["subjects"].items():
                assert blk["source_url"] == mod.PAGES[year][subj]
                validate_rows(blk["rows"])
                assert blk["rows"][0][0] == 700


def test_new_adapters_raise_on_gap_year():
    import rank_sync.provinces as P
    for prov in NEW_PROVS:
        mod = P.REGISTRY[prov]
        for year, why in mod.KNOWN_GAPS.items():
            try:
                mod.parse(year)
            except ValueError as e:
                assert str(e), f"{prov} {year} 缺口原因不能为空"
                assert year not in mod.PAGES
            else:  # pragma: no cover - 有 PAGES 就不该在 KNOWN_GAPS 里
                raise AssertionError(f"{prov} {year} 声明为缺口却能解析: {why}")


def test_overview_counts_after_unblock():
    """看板：9 省从 blocked 转到 ready，硬阻碍只剩西藏/新疆。"""
    from rank_sync import BLOCKED, overview
    ov = overview()
    for prov in NEW_PROVS:
        assert prov not in BLOCKED, prov
        row = next(r for r in ov["provinces"] if r["province"] == prov)
        assert row["status"] == "ready", (prov, row["status"])
    assert ov["counts"]["ready"] == 29, ov["counts"]
    assert ov["counts"]["blocked"] == 2, ov["counts"]
    assert set(BLOCKED) == {"西藏", "新疆"}


if __name__ == "__main__":
    unittest.main()
