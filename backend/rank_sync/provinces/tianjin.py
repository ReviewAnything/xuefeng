"""天津：gaokao.eol.cn 第三方文本转录（高考总成绩分数段统计）。

天津市教育招生考试院（zhaokao.net）仅 HTTP 可达、HTTPS 走代理不通，且
2022/2024/2025 对应页均无表格层；eol 2023 有标准 ``<tr><td>`` 文本表，可解析。

天津为 3+3 综合改革，**不分物理类/历史类**，只有一个全体考生的分布，故
``SUBJECTS = ["综合"]``（与山东同口径，勿当物理/历史类用）。

数据治理：``data_source=third_party_text``（绝不冒充 official），带 ``source_url``；
仅作学习参考，正式填报以天津市教育招生考试院官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "天津"
SITE = "https://gaokao.eol.cn"
SCHEME = "3+3"
SUBJECTS = ["综合"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；天津官方站 HTTPS 沙箱不通、"
        "2022/2024/2025 页无表格层，不 OCR；3+3 综合=全体考生，"
        "非物理/历史类；正式填报以天津市教育招生考试院为准")

PAGES = {
    2023: {
        "综合": "https://gaokao.eol.cn/tian_jin/dongtai/202306/t20230624_2446639.shtml",
    },
}
KNOWN_GAPS = {
    2022: "天津 2022 eol 页为图片、官方站 HTTPS 沙箱不通——不 OCR",
    2024: "天津 2024 eol 页为图片、官方站 HTTPS 沙箱不通——不 OCR",
    2025: "天津 2025 eol 页为图片、官方站 HTTPS 沙箱不通——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
