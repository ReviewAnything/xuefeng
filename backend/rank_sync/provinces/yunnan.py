"""云南：gaokao.eol.cn 第三方文本转录（高考成绩分数段统计表）。

云南省招生考试院五年正文**均是一张竖长 PNG**（2022 580×11829、2026 900×8615），
无表格层、无附件；「公示公告」25 页、「政策文件」4 页也无同类条目。按既定纪律
不 OCR。eol 2023 有标准 ``<tr><td>`` 文本表（理科正文 + 文科 ``_1`` 分页），可解析。
2022 / 2024 / 2025 的 eol 页为图片页，登记为 KNOWN_GAPS。

数据治理：``data_source=third_party_text``（绝不冒充 official），每个科类带
``source_url``；仅作学习参考，正式填报以云南省招生考试院官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "云南"
SITE = "https://gaokao.eol.cn"
SCHEME = "文理分科"
SUBJECTS = ["理科", "文科"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；云南官方分数段统计表为竖长 PNG，"
        "2022/2024/2025 eol 亦为图片页，沙箱内不 OCR；正式填报以云南省招生考试院为准")

PAGES = {
    2023: {
        "理科": "https://gaokao.eol.cn/yun_nan/dongtai/202306/t20230623_2446437.shtml",
        "文科": "https://gaokao.eol.cn/yun_nan/dongtai/202306/t20230623_2446437_1.shtml",
    },
}
KNOWN_GAPS = {
    2022: "云南 2022 官方为 PNG、eol 页为图片——不 OCR",
    2024: "云南 2024 官方为 PNG、eol 页为图片——不 OCR",
    2025: "云南 2025 官方为 PNG、eol 页为图片——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
