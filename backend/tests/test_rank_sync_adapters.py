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
    with mock.patch.object(henan, "http_get_html", return_value=_HENAN_HTML):
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


if __name__ == "__main__":
    unittest.main()
