"""福建：gaokao.eol.cn 第三方文本转录（考生成绩分布）。

福建省教育考试院的成绩分布**以图片发布**（转载页引用 wl-01.jpg 等 4 张/科类），
无文本层、无附件；eol 2022 / 2023 同样是图片页（0 个 ``<tr>``）。
2024 / 2025 的 eol 页为标准 ``<tr><td>`` 文本表，可解析。

坑：福建源表把关键批次线所在行标注成「520（特招线）」「441（本科线）」
「235（专科线）」，严格 ``fullmatch(r"\\d{3}")`` 会整行丢掉 -> 累计链断裂。
已在 ``common.parse_html_table`` 统一取前导整数（区间行除外）。

数据治理：``data_source=third_party_text``（绝不冒充 official），每个科类带
``source_url``；仅作学习参考，正式填报以福建省教育考试院官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "福建"
SITE = "https://gaokao.eol.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；福建官方成绩分布以图片发布，"
        "2022/2023 eol 亦为图片页，沙箱内不 OCR；正式填报以福建省教育考试院为准")

PAGES = {
    2025: {
        "物理类": "https://gaokao.eol.cn/fu_jian/dongtai/202507/t20250702_2678456.shtml",
        "历史类": "https://gaokao.eol.cn/fu_jian/dongtai/202507/t20250702_2678457.shtml",
    },
    2024: {
        "物理类": "https://gaokao.eol.cn/fu_jian/dongtai/202406/t20240625_2619344.shtml",
        "历史类": "https://gaokao.eol.cn/fu_jian/dongtai/202406/t20240625_2619342.shtml",
    },
}
KNOWN_GAPS = {
    2022: "福建 2022 官方与 eol 均为图片发布——不 OCR",
    2023: "福建 2023 官方与 eol 均为图片发布——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
