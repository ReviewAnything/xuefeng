"""江苏：gaokao.eol.cn 第三方文本转录（逐分段统计表）。

江苏省教育考试院「逐分段统计表」通知页**只挂 JPG 图片**（44 张，无表格层、
无附件）；eol 2022 / 2024 同样只有图片页。2025 的 eol 页是标准 ``<tr><td>``
文本表，可解析。2023 未探到任何文本形态（eol 亦无该年条目）。

坑：江苏源表把顶部截断桶印成区间行「658-750」，且单元格里混了 ``&nbsp;`` 实体
（``657&nbsp;``）——两者都会让 ``isdigit()`` 失败，已在 ``common.parse_html_table``
统一处理（unescape 实体 + 前导整数取分，区间行仍按顶部截断桶处理）。

数据治理：``data_source=third_party_text``（绝不冒充 official），每个科类带
``source_url``；仅作学习参考，正式填报以江苏省教育考试院官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "江苏"
SITE = "https://gaokao.eol.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；江苏官方逐分段统计表只挂 JPG 图片，"
        "2022/2024 eol 亦为图片页，沙箱内不 OCR；正式填报以江苏省教育考试院为准")

PAGES = {
    2025: {
        "历史类": "https://gaokao.eol.cn/jiang_su/dongtai/202506/t20250625_2676968.shtml",
        "物理类": "https://gaokao.eol.cn/jiang_su/dongtai/202506/t20250625_2676969.shtml",
    },
}
KNOWN_GAPS = {
    2022: "江苏 2022 官方与 eol 均为图片发布——不 OCR",
    2023: "江苏 2023 未探到文本形态（官方图片、eol 无该年条目）",
    2024: "江苏 2024 官方与 eol 均为图片发布——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
