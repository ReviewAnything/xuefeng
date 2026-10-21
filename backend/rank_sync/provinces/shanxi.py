"""山西：sxkszx.cn 官方「普通高考成绩一分一段统计表」HTML 双栏表。

官方站点为纯文本 HTML（非图片 / 非 PDF），可直接解析，无 OCR、无第三方依赖。
每年分「文史类」「理工类」两篇，各一篇独立页面；正文是一张 WIDTH:21cm 的数据表，
每行 6 个单元格（分数 | 本分人数 | 累计人数 各两份），实为同一分布按高 / 低分
拆成左右两栏印刷。解析时把所有三元组抽出、按分数降序重排即恢复为单分布。

校验：分数严格降序、累计链连续（common.validate_rows）。
"""
from __future__ import annotations

import hashlib
import re

from ..common import http_get_html, sha256, validate_rows, now_iso

PROVINCE = "山西"
SITE = "http://www.sxkszx.cn"
SCHEME = "文理分科"
SUBJECTS = ["文史类", "理工类"]
STATUS = "ready"

# 各年两个科类的通知页（站点静态路径，逐年登记）。
# 2024 用「文史类 / 理工类」命名；2025 起改为「历史科目组合 / 物理科目组合」。
# 2022/2023 官方页为「文史类 + 理工类」合并单页（多个 <table> 同页），需按科类切分
# 解析，暂缓登记为 KNOWN_GAPS（不臆造第三方源、不把两分布混为一谈）。
PAGES = {
    2025: {
        "历史科目组合": "http://sxkszx.cn/news/2025625/n6415125868.html",
        "物理科目组合": "http://sxkszx.cn/news/2025625/n7121125869.html",
    },
    2024: {
        "文史类": "http://sxkszx.cn/news/2024624/n3849122419.html",
        "理工类": "http://sxkszx.cn/news/2024624/n3013122420.html",
    },
}
KNOWN_GAPS = {
    2022: "山西 2022 官方页为文史+理工合并单页，需按科类切分解析（暂缓）",
    2023: "山西 2023 官方页为文史+理工合并单页，需按科类切分解析（暂缓）",
}

_HDR = ["分数", "本分人数", "累计人数"]


def _parse_double_table(html: str) -> list[list[int]]:
    """山西数据表为双栏：每行 6 个单元格（分数|本分人数|累计人数 各两份），
    实为同一分布按高 / 低分拆成左右两栏印刷。

    与版式解耦：不依赖表格 width 属性，直接扫描整页所有 ``<tr>``，对每行每 3 个
    非空单元格取一组（分数 | 本分人数 | 累计人数）。表头行（分数/本分人数/累计人数）
    首格非数字，自然被跳过；导航 / 标题单元格同理。所有三元组收集后按分数降序重排
    即恢复单分布（累计链天然连续）。
    """
    rows: list[list[int]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [
            re.sub(r"<[^>]+>", "", c).replace("&nbsp;", "").replace("　", "").strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        ]
        cells = [c for c in cells if c != ""]
        for k in range(0, len(cells) - 2, 3):
            a, b, c = cells[k], cells[k + 1], cells[k + 2]
            m = re.match(r"(\d+)", a)
            if m and b.isdigit() and c.isdigit():
                rows.append([int(m.group(1)), int(b), int(c)])
    if not rows:
        raise ValueError("未解析出任何数据行（可能是图片 / 结构变化）")
    rows.sort(key=lambda r: -r[0])
    return rows


def parse(year: int) -> dict:
    pages = PAGES.get(year)
    if not pages:
        raise ValueError(KNOWN_GAPS.get(year, "该年未登记通知页"))
    subjects: dict = {}
    blobs: list[bytes] = []
    for subj, url in pages.items():
        html = http_get_html(url, timeout=60)
        blob = html.encode("utf-8")
        blobs.append(blob)
        rows = _parse_double_table(html)
        validate_rows(rows)
        subjects[subj] = {"rows": rows, "source_url": url,
                          "source_sha256": sha256(blob)}
    return {
        "meta": {
            "year": year,
            "province": PROVINCE,
            "data_source": "official",
            "source_url": next(iter(pages.values())),
            "subject_scheme": SCHEME,
            "source_sha256": sha256(b"".join(blobs)),
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
