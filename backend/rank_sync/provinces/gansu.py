"""甘肃：gaokao.eol.cn 第三方文本转录（高考成绩分段表）。

甘肃省教育考试院站点（ganseea.cn）首页可达但栏目页超时，未取到官方原表；
eol 2023 / 2025 有标准 ``<tr><td>`` 文本表，可解析。2022 / 2024 的 eol 页为
图片页（0 个 ``<tr>``），登记为 KNOWN_GAPS。

科类口径随改革变化，沿用源站标签，不擅自归一：
- 2023（老文理）：``文史类`` / ``理工类``；
- 2025（3+1+2）：``历史类`` / ``物理类``。

数据治理：``data_source=third_party_text``（绝不冒充 official），每个科类带
``source_url``；仅作学习参考，正式填报以甘肃省教育考试院官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "甘肃"
SITE = "https://gaokao.eol.cn"
SCHEME = "文理分科→3+1+2"
SUBJECTS = ["文史类", "理工类", "历史类", "物理类"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；甘肃官方站点栏目页沙箱超时，"
        "2022/2024 eol 页为图片，沙箱内不 OCR；2023 为老文理、2025 为 3+1+2，"
        "科类标签沿用源站；正式填报以甘肃省教育考试院为准")

PAGES = {
    2025: {
        "历史类": "https://gaokao.eol.cn/gan_su/dongtai/202507/t20250702_2678473.shtml",
        "物理类": "https://gaokao.eol.cn/gan_su/dongtai/202507/t20250702_2678474.shtml",
    },
    2023: {
        "文史类": "https://gaokao.eol.cn/gan_su/dongtai/202306/t20230625_2447000.shtml",
        "理工类": "https://gaokao.eol.cn/gan_su/dongtai/202306/t20230625_2447001.shtml",
    },
}
KNOWN_GAPS = {
    2022: "甘肃 2022 eol 页为图片、官方站点沙箱超时——不 OCR",
    2024: "甘肃 2024 eol 页为图片（物理+历史合并单页）——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
