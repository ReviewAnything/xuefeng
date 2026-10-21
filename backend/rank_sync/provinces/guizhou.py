"""贵州：gaokao.eol.cn 第三方文本转录（高考分数段统计表）。

贵州省招生考试院站点在沙箱内直连不可达（www.eaagz.org.cn 代理层 502 / 超时），
无法取官方原表；eol 2023 有标准 ``<tr><td>`` 文本表（理工 / 文史各一篇），可解析。
2022 / 2024 / 2025 的 eol 页为图片页（0 个 ``<tr>``），登记为 KNOWN_GAPS。

数据治理：``data_source=third_party_text``（绝不冒充 official），每个科类带
``source_url``；仅作学习参考，正式填报以贵州省招生考试院官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "贵州"
SITE = "https://gaokao.eol.cn"
SCHEME = "文理分科"
SUBJECTS = ["理工类", "文史类"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；贵州官方站点沙箱不可达，"
        "2022/2024/2025 eol 页为图片，沙箱内不 OCR；正式填报以贵州省招生考试院为准")

PAGES = {
    2023: {
        "理工类": "https://gaokao.eol.cn/gui_zhou/dongtai/202306/t20230624_2446816.shtml",
        "文史类": "https://gaokao.eol.cn/gui_zhou/dongtai/202306/t20230624_2446817.shtml",
    },
}
KNOWN_GAPS = {
    2022: "贵州 2022 eol 页为图片、官方站点沙箱不可达——不 OCR",
    2024: "贵州 2024 eol 页为图片、官方站点沙箱不可达——不 OCR",
    2025: "贵州 2025 eol 页为图片、官方站点沙箱不可达——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
