"""海南：gaokao.eol.cn 第三方文本转录（普通高考考生成绩分布表）。

海南省考试局（ea.hainan.gov.cn）站点可达，但 2022 / 2024 对应页无表格层；
eol 2023 / 2025 有标准 ``<tr><td>`` 文本表，可解析。

海南为 3+3 综合改革，**不分物理类/历史类**，只有一个全体考生的分布，故
``SUBJECTS = ["综合"]``。另注意海南用**标准分**（满分 900，非 750），
位次与分数都不可与其它省直接横比。

数据治理：``data_source=third_party_text``（绝不冒充 official），带 ``source_url``；
仅作学习参考，正式填报以海南省考试局官方发布为准。
"""
from __future__ import annotations

from ..common import doc_from_html_pages

PROVINCE = "海南"
SITE = "https://gaokao.eol.cn"
SCHEME = "3+3"
SUBJECTS = ["综合"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

NOTE = ("第三方文本转录（gaokao.eol.cn）；海南 2022/2024 页无表格层，不 OCR；"
        "3+3 综合=全体考生；且为标准分（满分 900，非 750），"
        "不可与其它省分数直接横比；正式填报以海南省考试局为准")

PAGES = {
    2025: {
        "综合": "https://gaokao.eol.cn/hai_nan/dongtai/202507/t20250702_2678468.shtml",
    },
    2023: {
        "综合": "https://gaokao.eol.cn/hai_nan/dongtai/202306/t20230625_2446964.shtml",
    },
}
KNOWN_GAPS = {
    2022: "海南 2022 官方与 eol 页均无表格层（图片）——不 OCR",
    2024: "海南 2024 官方与 eol 页均无表格层（图片）——不 OCR",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记文章页"))
    return doc_from_html_pages(PROVINCE, year, pages, scheme=SCHEME,
                               data_source=DATA_SOURCE, note=NOTE)
