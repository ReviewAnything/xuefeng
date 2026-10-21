"""辽宁：lnzsks.com「普通高校招生考试成绩统计表」（3+1+2，物理/历史各一份 PDF）。

版式（2023–2026 一致，与浙江/安徽的并排多组同族）：
- 每页横排 **4 组**「分数 | 人数 累计人数」，列位置由**表头 `分数` 的 x 坐标**给出
  （第 1 页表头出现 4 次，正好是 4 组锚点），组宽 = 相邻锚点差；
- **人数与累计有时在同一格**（`217   6,245`）、**有时是两个独立单元格**
  （`217` 在 214、`6,245` 在 254），所以按「该锚点区间内的所有数字」依次取
  分数→人数→累计，不能按固定单元格序号取；
- 累计带千分位逗号（`6,028`），必须先去掉逗号再转 int；
- 顶部 `708 及以上` 是截断桶：`及以上` 是分数下方的一个独立文本，人数=累计，打 `top_note`；
- **0 人的分数段官方不印**（2023 历史有 6 处、2025 物理 2 处），累计链仍自洽 →
  允许分数不连续，缺口记进 `subjects.*.omitted_scores`（这是口径事实，不是漏行）。

口径：
- 物理学科类/历史学科类两表，**不含**体育·/艺术·同类表（正文页上这两类排在后面，
  靠 PDF 首页标题里有没有「体育」「艺术」挡掉）；
- 表内人数为**高考总分（含政策加分）**口径，表头未另注。

2022 年官方只发了 4 张 PNG（`up_img/advimg/2022-06-23_*.png`），无 PDF 无文本层，
按纪律不 OCR，整年进 `KNOWN_GAPS`。
"""
from __future__ import annotations

import logging
import re

import requests

from ..common import decode_html, http_get, now_iso, sha256, validate_rows

PROVINCE = "辽宁"
SITE = "https://www.lnzsks.com"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

# 每年：公告页（可点开源溯）+ 两份 PDF（物理在前、历史在后，2023 起都是这个顺序）
SOURCES = {
    2023: {"notice": SITE + "/newsinfo/IMS_20230624_42868_eCUcfo9HS2.htm",
           "pdfs": {"物理类": SITE + "/lnzkbfiles/2023/2023gkfsx06240YmeDfvVEdN1%20.pdf",
                    "历史类": SITE + "/lnzkbfiles/2023/2023gkfsx06240WRyku9gNVY2.pdf"}},
    2024: {"notice": SITE + "/newsinfo/IMS_20240624_44046_Zy6XwhnIQA.htm",
           "pdfs": {"物理类": SITE + "/lnzkbfiles/2024/2024gkfsxptl0624001.pdf",
                    "历史类": SITE + "/lnzkbfiles/2024/2024gkfsxptw0624002.pdf"}},
    2025: {"notice": SITE + "/newsinfo/IMS_20250624_44986_sc2NoSdwf5.htm",
           "pdfs": {"物理类": SITE + "/lnzkbfiles/2025/2025gk1f1d0624wl001.pdf",
                    "历史类": SITE + "/lnzkbfiles/2025/2025gk1f1d0624ls002.pdf"}},
    2026: {"notice": SITE + "/newsinfo/IMS_20260624_46117_xCuXJ7lN6W.htm",
           "pdfs": {"物理类": SITE + "/lnzkbfiles/2026/lns2026gkcjtjb0624clhptll01.pdf",
                    "历史类": SITE + "/lnzkbfiles/2026/lns2026gkcjtjb0624clhptlw02.pdf"}},
}

# 缺口的实证原因（不 OCR、不臆造）
KNOWN_GAPS = {
    2022: ("公告页 IMS_20220623_41576 只挂了 4 张 PNG（up_img/advimg/2022-06-23_*.png），"
           "分科类子页同样只有图片，无 PDF/文本层——不 OCR"),
}

TITLE_PAT = re.compile(
    r"^(?:辽宁省)?20\d{2}年(?:辽宁省)?普通高校招生考试成绩统计表[（(](物理|历史)学科类[)）]$")
NUM_PAT = re.compile(r"[\d,]+")
SEARCH_URL = SITE + "/lnzsksSearch/search/index.action"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PDF_LINK_PAT = re.compile(r'href="([^"]+\.pdf)"', re.I)


def _page_groups(page, tol: float = 3.0):
    """一页的文本行按 y 聚成视觉行，行内按 x 从左到右。"""
    from pdfminer.layout import LTTextContainer, LTTextLineHorizontal

    items = []
    for el in page:
        if isinstance(el, LTTextContainer):
            for ln in el:
                if isinstance(ln, LTTextLineHorizontal):
                    t = ln.get_text().strip()
                    if t:
                        items.append((round(ln.y0, 1), round(ln.x0, 1), t))
    groups: list[list[tuple[float, float, str]]] = []
    for rec in sorted(items, key=lambda r: -r[0]):
        if groups and abs(rec[0] - groups[-1][0][0]) <= tol:
            groups[-1].append(rec)
        else:
            groups.append([rec])
    return [sorted(g, key=lambda c: c[1]) for g in groups]


def _anchors(groups) -> list[float]:
    """组锚点 = 表头里 `分数` 的 x 坐标（每页重复，取第一份即整页通用）。"""
    for g in groups:
        xs = [x for _y, x, t in g if t == "分数"]
        if len(xs) >= 2:
            return sorted(xs)
    return []


def _rows_from_groups(groups) -> tuple[list[list[int]], list[float], list[str]]:
    """「视觉行」列表 -> (数据行, 组锚点, 未解析行)。纯函数，便于脱网测版式。"""
    anchors = _anchors(groups)
    rows: list[list[int]] = []
    dropped: list[str] = []
    if not anchors:
        return rows, [], dropped
    width = anchors[1] - anchors[0] if len(anchors) > 1 else 130.0
    for g in groups:
        joined = " ".join(t for _y, _x, t in g)
        if "成绩统计表" in joined:            # 每页都印的表名行
            continue
        if "分数" in joined and "人数" in joined:      # 表头行
            continue
        for a in anchors:
            nums = [int(n.replace(",", ""))
                    for _y, x, txt in g if a - 5 <= x < a + width - 5
                    for n in NUM_PAT.findall(txt)]
            if not nums:
                continue                       # 该组在本页提前结束（末页常见）
            if len(nums) == 3:
                rows.append(nums)
            else:
                dropped.append(f"{a:.0f}:{'/'.join(str(n) for n in nums)}")
    return rows, anchors, dropped


def _omitted(rows: list[list[int]]) -> list[int]:
    """官方不印的「0 人分数段」——累计链仍自洽，属口径事实，不是漏行。"""
    seen = {r[0] for r in rows}
    return [s for s in range(rows[0][0], rows[-1][0], -1) if s not in seen]


def parse_pdf(blob: bytes) -> tuple[list[list[int]], str, list[int], str, str]:
    """PDF -> (rows, top_note, omitted_scores, title, subject)。"""
    import tempfile
    from pathlib import Path

    from pdfminer.high_level import extract_pages

    logging.getLogger("pdfminer").setLevel(logging.ERROR)   # 2023 的 PDF 带禁止抽取元数据
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(blob)
        path = f.name
    rows: list[list[int]] = []
    dropped: list[str] = []
    title = ""
    try:
        for page in extract_pages(path):
            groups = _page_groups(page)
            if not title:
                for g in groups:
                    hit = [t for _y, _x, t in g if "成绩统计表" in t]
                    if hit:
                        title = hit[0]
                        break
            page_rows, _anchors_, page_dropped = _rows_from_groups(groups)
            rows.extend(page_rows)
            dropped.extend(page_dropped)
    finally:
        Path(path).unlink(missing_ok=True)
    m = TITLE_PAT.match(title)
    if not m:
        raise ValueError(f"辽宁 PDF 不是「(物理|历史)学科类成绩统计表」（标题：{title!r}），拒收")
    if dropped:
        raise ValueError(f"辽宁 PDF 有 {len(dropped)} 组行未解析（拒收整份）：{dropped[:3]}")
    rows.sort(key=lambda r: -r[0])
    if len(rows) < 200:
        raise ValueError(f"辽宁 PDF 只解析出 {len(rows)} 行，版式可能变了")
    validate_rows(rows)
    top_note = f"{rows[0][0]}↑" if rows[0][1] == rows[0][2] else ""
    subj = "物理类" if m.group(1) == "物理" else "历史类"
    return rows, top_note, _omitted(rows), title, subj


def discover(year: int) -> dict[str, str]:
    """站内搜索找该年的成绩统计表公告页（新年度免改代码，站内检索是 POST）。"""
    resp = requests.post(SEARCH_URL, data={"title": f"{year}年"}, timeout=60,
                         headers={"User-Agent": UA})
    page = decode_html(resp.content)
    for href, text in re.findall(r'href="([^"]+/newsinfo/[^"]+)"[^>]*>\s*([^<]{4,90})\s*<',
                                 page):
        if not re.search(rf"{year}年.*普通高校招生考试成绩统计表", text):
            continue
        if any(w in text for w in ("体育", "艺术", "专升本")):
            continue
        return {"notice": href if href.startswith("http") else SITE + href}
    raise ValueError(f"辽宁 {year} 成绩统计表公告页未找到")


def source(year: int) -> dict:
    return SOURCES.get(year) or discover(year)


def _pdfs_from_notice(notice: str) -> dict[str, str]:
    """公告页上的 PDF 按出现顺序取前两个（2023 起物理在前；顺序变了靠标题兜底）。"""
    page = decode_html(http_get(notice, timeout=90))
    urls = [h if h.startswith("http") else SITE + h for h in PDF_LINK_PAT.findall(page)]
    if len(urls) < 2:
        raise ValueError(f"辽宁公告页 PDF 不足两个: {notice}")
    return {"物理类": urls[0], "历史类": urls[1]}


def parse(year: int) -> dict:
    src = source(year)
    files = dict(src.get("pdfs") or _pdfs_from_notice(src["notice"]))
    subjects: dict = {}
    shas: dict[str, str] = {}
    floors: dict[str, int] = {}
    urls: dict[str, str] = {}
    for subj, url in files.items():
        blob = http_get(url, timeout=180)
        rows, top_note, omitted, _title, real_subj = parse_pdf(blob)
        if real_subj != subj:
            raise ValueError(f"辽宁 {year} PDF 科类不符：期望 {subj}，实得 {real_subj}")
        subjects[subj] = {"rows": rows, "top_note": top_note,
                          "omitted_scores": omitted, "total": rows[-1][2]}
        shas[subj] = sha256(blob)
        floors[subj] = rows[-1][0]
        urls[subj] = url
    if set(subjects) != set(SUBJECTS):
        raise ValueError(f"辽宁 {year} 科类不全：{sorted(subjects)}")
    return {
        "meta": {
            "year": year, "province": PROVINCE, "data_source": "official",
            "source_url": src["notice"],
            "subject_scheme": SCHEME,
            "columns": 3,
            "tracks": {"primary": "高考总分（含政策加分）"},
            "note": ("3+1+2 物理/历史各一表，每页并排 4 组；"
                     "0 人的分数段官方不印，缺口记 omitted_scores（不是漏行）；"
                     "体育·/艺术·同类表是另一口径，不并入"),
            "attachment_url_map": urls,
            "attachment_sha256_map": shas,
            # 顶层留一份「主附件」摘要（物理类），与湖北/湖南等单附件省的字段对齐
            "attachment_url": urls.get("物理类", ""),
            "attachment_sha256": shas.get("物理类", ""),
            "score_floor": floors,
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
