"""新疆：gk100.com 第三方文本转录（一分一段表）。

新疆教育考试院（xjzk.gov.cn）站点可达但未挂出可解析的一分一段文本表；
eol.cn 的「历年一分一段」hub 完全没有新疆条目。gk100.com 有完整文本表，
但**形态与 eol 不同**：一张 6 列宽表把文/理两科混在一起，靠第 4 列区分科类——

    ``分数 | 本段人数 | 累计人数 | 科类 | 省份 | 年份``
    ``641及以上 | 1 | 1 | 文科 | 新疆 | 2025``

所以 ``common.parse_html_table``（只认 3/5 列）用不了，这里按列切出科类再分组。

数据治理：``data_source=third_party_text``（绝不冒充 official），每行带
``source_url``；仅作学习参考，正式填报以新疆教育考试院官方发布为准。
"""
from __future__ import annotations

import re

from ..common import http_get_html, sha256, validate_rows, now_iso

PROVINCE = "新疆"
SITE = "https://www.gk100.com"
SCHEME = "文理分科"
SUBJECTS = ["文科", "理科"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gk100.com，6 列宽表：分数|本段|累计|科类|省份|年份）；"
        "新疆官方站未挂可解析文本表、eol hub 无新疆条目；"
        "正式填报以新疆教育考试院官方发布为准")

PAGES = {
    2025: "https://www.gk100.com/read_58631558.htm",
}
KNOWN_GAPS = {
    2022: "新疆 2022 未探到可解析的一分一段文本源（官方无表、eol 无条目）",
    2023: "新疆 2023 未探到可解析的一分一段文本源（官方无表、eol 无条目）",
    2024: "新疆 2024 未探到可解析的一分一段文本源（官方无表、eol 无条目）",
}

_TAG = re.compile(r"<[^>]+>")
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


def _parse_gk100_table(html: str, year: int) -> dict[str, list[list[int]]]:
    """6 列宽表 -> {科类: rows}。只收目标年份、科类为文科/理科的行。"""
    grouped: dict[str, list[list[int]]] = {}
    for tr in _TR.findall(html):
        cells = [re.sub(r"\s+", "", _TAG.sub("", c)) for c in _TD.findall(tr)]
        if len(cells) < 6:
            continue
        score, seg, cum, subj, _prov, y = cells[:6]
        if subj not in ("文科", "理科"):
            continue
        # 年份列是源表自带的，用它过滤——避免多期数据同页时串年
        m_year = re.match(r"(\d{4})", y)
        if not m_year or int(m_year.group(1)) != year:
            continue
        m = re.match(r"^(\d{2,3})", score)   # 顶行常写成「641及以上」
        if not m:
            continue
        if not (seg.isdigit() and cum.isdigit()):
            continue
        grouped.setdefault(subj, []).append([int(m.group(1)), int(seg), int(cum)])
    if not grouped:
        raise ValueError("未解析出任何数据行（可能是图片 / 结构变化）")
    for rows in grouped.values():
        rows.sort(key=lambda r: -r[0])
        validate_rows(rows)
    return grouped


def parse(year: int) -> dict:
    url = PAGES.get(year)
    if not url:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    html = http_get_html(url, timeout=60)
    grouped = _parse_gk100_table(html, year)
    blob = html.encode("utf-8")
    subjects = {
        subj: {"rows": rows, "source_url": url, "source_sha256": sha256(blob)}
        for subj, rows in grouped.items()
    }
    return {
        "meta": {
            "year": year,
            "province": PROVINCE,
            "data_source": DATA_SOURCE,
            "source_url": url,
            "subject_scheme": SCHEME,
            "note": NOTE,
            "source_sha256": sha256(blob),
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
