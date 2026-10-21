"""河南：gaokao.eol.cn 第三方文本转录（一分一段表）。

河南省教育考试院官网（haeea.cn）返回 412 反爬、heao.com.cn 官方 PDF 为图片型
（pdfminer 抽不出文本），沙箱内均不可直接取数。按既定政策，采用
「经核实的第三方文本转录」：中国教育在线（gaokao.eol.cn）完整发布河南一分一段表，
表结构为标准 ``<tr><td>``（分数 | 人数 | 累计人数），可由 ``parse_html_table`` 解析。

数据治理：``data_source=third_party_text``（绝不冒充 official），每行带 ``source_url``；
仅作学习参考，正式填报以河南省教育考试院官方发布为准。
"""
from __future__ import annotations

from ..common import http_get_html, parse_html_table, validate_rows, now_iso

PROVINCE = "河南"
SITE = "https://gaokao.eol.cn"
SCHEME = "文理分科"
SUBJECTS = ["文科", "理科"]
STATUS = "ready"
DATA_SOURCE = "third_party_text"

# 各年两个科类的第三方文本页（中国教育在线）。2022–2024 为文理分科。
# 2022 eol 页为非表格形态（缺累计列），暂不可解析，登记为 KNOWN_GAPS。
PAGES = {
    2024: {
        "文科": "https://gaokao.eol.cn/he_nan/dongtai/202406/t20240625_2619212.shtml?fromcoop=bdzhc",
        "理科": "https://www.eol.cn/m/gaokao/202406/t20240625_2619212_1.shtml",
    },
    2023: {
        "文科": "https://gaokao.eol.cn/he_nan/dongtai/202306/t20230625_2446851.shtml?fromcoop=bdzhc",
        "理科": "https://gaokao.eol.cn/he_nan/dongtai/202306/t20230625_2446847.shtml?fromcoop=bdzhc",
    },
}
KNOWN_GAPS = {
    2022: "河南 2022 eol 页非表格形态（缺累计列），第三方链接待探明",
    2025: "河南 2025 一分一段表（物理 / 历史类）第三方链接待探明",
}


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记通知页"))
    subjects: dict = {}
    for subj, url in pages.items():
        html = http_get_html(url, timeout=60)
        rows, top, below = parse_html_table(html)
        validate_rows(rows)
        blk: dict = {"rows": rows, "source_url": url}
        if top:
            blk["top_note"] = top
        if below:
            blk["below_bucket"] = below
        subjects[subj] = blk
    return {
        "meta": {
            "year": year,
            "province": PROVINCE,
            "data_source": DATA_SOURCE,
            "source_url": next(iter(pages.values())),
            "subject_scheme": SCHEME,
            "note": ("第三方文本转录（gaokao.eol.cn）；河南官方 haeea.cn 反爬、heao.com.cn "
                     "官方 PDF 为图片型，沙箱不可取；正式填报以河南省教育考试院为准"),
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
