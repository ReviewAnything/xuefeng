"""河北：gaokao.eol.cn 第三方文本转录（一分一段表）。

河北省教育考试院的四份官方 PDF **均为扫描件**（pdfminer 抽 0 行），按既定纪律
不 OCR；中国教育在线 2023 / 2024 有标准 ``<tr><td>`` 文本表，可解析。
2022 与 2025 的 eol 页为图片页（0 个 ``<tr>``），登记为 KNOWN_GAPS。

数据治理：``data_source=third_party_text``（绝不冒充 official），每个科类带
``source_url``；仅作学习参考，正式填报以河北省教育考试院官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "河北"
SITE = "https://gaokao.eol.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；河北官方一分一段表为扫描件 PDF，"
        "2022/2025 eol 页为图片，沙箱内不 OCR；正式填报以河北省教育考试院为准")

PAGES = {
    2024: {
        "历史类": "https://gaokao.eol.cn/he_bei/dongtai/202406/t20240625_2619073.shtml",
        "物理类": "https://gaokao.eol.cn/he_bei/dongtai/202406/t20240625_2619074.shtml",
    },
    2023: {
        "历史类": "https://gaokao.eol.cn/he_bei/dongtai/202306/t20230625_2446944.shtml",
        "物理类": "https://gaokao.eol.cn/he_bei/dongtai/202306/t20230625_2446858.shtml",
    },
}
KNOWN_GAPS = {
    2022: "河北 2022 官方 PDF 为扫描件、eol 页为图片——不 OCR",
    2025: "河北 2025 官方 PDF 为扫描件、eol 页为图片——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
