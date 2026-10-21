"""四川：gaokao.eol.cn 第三方文本转录（一分一段表）。

四川省教育考试院的一分一段表**只以图片发布**（通知页正文 26 张 JPG，无文本层、
无附件）；中国教育在线 2022–2024 同样是图片页（正文 0 个 ``<tr>``、50+ 张图），
按既定纪律不 OCR、不臆造。2025 起 eol 同时提供标准 ``<tr><td>`` 文本表，可解析。

数据治理：``data_source=third_party_text``（绝不冒充 official），每个科类带
``source_url``；仅作学习参考，正式填报以四川省教育考试院官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "四川"
SITE = "https://gaokao.eol.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；四川官方一分一段表仅以图片发布，"
        "2022–2024 eol 亦为图片页，沙箱内不 OCR；正式填报以四川省教育考试院为准")

# 2025 为四川首届新高考（3+1+2），两个科类各一篇文本页。
# 2022–2024 官方与 eol 均为图片，登记为 KNOWN_GAPS。
PAGES = {
    2025: {
        "物理类": "https://gaokao.eol.cn/si_chuan/dongtai/202507/t20250702_2678480.shtml",
        "历史类": "https://gaokao.eol.cn/si_chuan/dongtai/202507/t20250702_2678481.shtml",
    },
}
KNOWN_GAPS = {
    2022: "四川 2022 官方与 eol 均为图片发布（无文本层、无附件）——不 OCR",
    2023: "四川 2023 官方与 eol 均为图片发布（无文本层、无附件）——不 OCR",
    2024: "四川 2024 官方与 eol 均为图片发布（无文本层、无附件）——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
