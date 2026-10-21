"""上海：shmeea.edu.cn「考生高考成绩分布表」（3+3，全市一张「综合」表），2022–2026。

形态：每年一份 PDF，4–7 页，每页**一整块**「分数|人数|累计人数」（不像浙江/安徽
那样并排多组），所以按 y 聚行、按 x 排三格即可，不需要列簇聚类。

口径（官方表自带，别臆造）：
- **3+3，全市一张「综合」表**，不分物理类/历史类，`SUBJECTS = ["综合"]`；
  满分 660，分数恒为三位数（艺术类那种 500+ 的综合分表不在这里）；
- 顶部是截断桶 `616分及以上` / `619分及以上`（人数 = 累计），打 `top_note`；
- **覆盖范围逐年变过，跨年比较位次前必须先看 `coverage` + `score_floor`**：
  2022 印到 280、2023 印到 284（全分数段）；2024 起改印「**本科录取控制分数线
  上**考生」分布表，止于本科线（2024/2026 都止于 403）。同一个人在不同年份的
  位次差，落在截断段以下时不可比；
- 2025 官方只发了**扫描件 PDF**（4 页图片、0 个字符），按纪律不 OCR、
  不臆造，整年进 `KNOWN_GAPS`；
- 艺术类/体育类/综合评价批次的分布表是**另一个口径**（专业统考成绩 / 投档成绩 /
  入围考生），不并入本表；正文页上它们排在普通类之后，解析时靠 PDF 首页标题
  `20XX年考生高考成绩分布表` 严格匹配来排除。
"""
from __future__ import annotations

import re

from ..common import decode_html, http_get, now_iso, sha256, validate_rows

PROVINCE = "上海"
SITE = "https://www.shmeea.edu.cn"
SCHEME = "3+3"
SUBJECTS = ["综合"]
STATUS = "ready"

# 每年：正文页（可点开源溯）+ 普通类成绩分布表 PDF
# 附件路径五年四个样，别想按规则拼：2022 /ytl/00.pdf、2023 /2_0.pdf、
# 2024 /00.pdf、2025–2026 /2/0.pdf（2026 的 2 目录下 0..11 张，0 才是普通类）。
SOURCES = {
    2022: {"notice": SITE + "/page/08000/20220723/16584.html",
           "data": SITE + "/download/20220723/ytl/00.pdf"},
    2023: {"notice": SITE + "/page/08000/20230623/17660.html",
           "data": SITE + "/download/20230623/2_0.pdf"},
    2024: {"notice": SITE + "/page/02200/20240623/18612.html",
           "data": SITE + "/download/20240623/00.pdf"},
    2026: {"notice": SITE + "/page/02200/20260623/20375.html",
           "data": SITE + "/download/20260623/2/0.pdf"},
}

# 表底覆盖范围的逐年事实（从官方表实际印到的最后一行读出）
COVERAGE = {
    2022: "全分数段",
    2023: "全分数段",
    2024: "本科录取控制分数线上考生",
    2025: "本科录取控制分数线上考生",
    2026: "本科录取控制分数线上考生",
}

# 缺口的实证原因（不 OCR、不臆造；拿到机读原表再补）
KNOWN_GAPS = {
    2025: ("公告页 /page/02200/20250623/19540.html 只挂扫描件 PDF"
           "（4 页各 1 张图、pdfminer 抽出 0 个字符），无文本层——不 OCR"),
}

# 栏目页第 N 页：index.html / index_2.html / index_3.html ...
# 2024 起发在「秋季高考」(02200)，2022/2023 只发在「消息速递」(08000)——两个栏目都要翻。
SECTIONS = ("02200", "08000")
LIST_TPL = SITE + "/page/%s/%s"

TITLE_PAT = re.compile(r"^(20\d{2})年考生高考成绩分布表$")
TOP_PAT = re.compile(r"^(\d{3})\s*分及以上$")
SCORE_PAT = re.compile(r"^(\d{3})$")
FOOTER_PAT = re.compile(r"^第\s*\d+\s*页")
# 表尾注：2022 是一句「注：体育类…另行公布」，2024 起拆成「注：」+ 编号 1./2./3./4.
NOTE_PAT = re.compile(r"^(?:注[:：]|\d+\s*[.、])")
HEAD_WORDS = ("分数", "人数", "累计人数")
NEWS_TITLE_PAT = re.compile(r"(20\d{2})年.*成绩分布表")
PDF_LINK_PAT = re.compile(r'href="([^"]+\.pdf)"', re.I)


def _page_groups(page, tol: float = 3.0):
    """把一页的文本行按 y 聚成「视觉行」，行内按 x 从左到右。"""
    from pdfminer.layout import LTTextContainer, LTTextLineHorizontal

    lines = []
    for el in page:
        if isinstance(el, LTTextContainer):
            for ln in el:
                if isinstance(ln, LTTextLineHorizontal):
                    t = ln.get_text().strip()
                    if t:
                        lines.append((round(ln.y0, 1), round(ln.x0, 1), t))
    groups: list[list[tuple[float, float, str]]] = []
    for rec in sorted(lines, key=lambda r: -r[0]):
        if groups and abs(rec[0] - groups[-1][0][0]) <= tol:
            groups[-1].append(rec)
        else:
            groups.append([rec])
    return [sorted(g, key=lambda c: c[1]) for g in groups]


def _is_noise(cells: list[str]) -> bool:
    """版式噪声：页脚、表头、表尾注（`注：` / `1.` / 含「公布」的说明句）。"""
    joined = " ".join(cells)
    if any(FOOTER_PAT.match(c) for c in cells):
        return True
    if any(w in joined for w in HEAD_WORDS):
        return True
    return bool(NOTE_PAT.match(cells[0])) or "公布" in joined


def _row_of(cells: list[str]) -> list[int] | None:
    """三格行 -> [分数, 人数, 累计]；不是数据行返回 None。"""
    head, seg, cum = cells
    m = TOP_PAT.match(head) or SCORE_PAT.match(head)
    if not m or not (seg.isdigit() and cum.isdigit()):
        return None
    return [int(m.group(1)), int(seg), int(cum)]


def parse_pdf(blob: bytes) -> tuple[list[list[int]], str, str, list[str]]:
    """PDF -> (rows, top_note, title, dropped)。"""
    import tempfile
    from pathlib import Path

    from pdfminer.high_level import extract_pages

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(blob)
        path = f.name
    rows: list[list[int]] = []
    dropped: list[str] = []
    title = ""
    try:
        for page in extract_pages(path):
            for g in _page_groups(page):
                cells = [c[2] for c in g]
                if len(cells) != 3:
                    joined = " ".join(cells)
                    if not title and TITLE_PAT.match(joined):
                        title = joined
                        continue
                    if _is_noise(cells) or not joined.strip():
                        continue
                    dropped.append(joined)
                    continue
                row = _row_of(cells)
                if row is None:
                    if _is_noise(cells):
                        continue
                    dropped.append(" | ".join(cells))
                    continue
                rows.append(row)
    finally:
        Path(path).unlink(missing_ok=True)
    rows.sort(key=lambda r: -r[0])
    if not TITLE_PAT.match(title):
        raise ValueError(f"上海 PDF 不是「考生高考成绩分布表」（标题：{title!r}），拒收")
    top_note = f"{rows[0][0]}↑" if rows and rows[0][1] == rows[0][2] else ""
    return rows, top_note, title, dropped


def _list_url(section: str, pno: int) -> str:
    return LIST_TPL % (section, "index.html" if pno == 1 else f"index_{pno}.html")


def discover(year: int) -> dict[str, str]:
    """在「秋季高考 / 消息速递」栏目里翻页找该年的成绩分布表条目（新年度免改代码）。

    列表页是服务端直出（`index_2.html` 就能翻页），条目带日期；翻到该年 6 月
    以前就停，避免无谓翻完几百页。
    """
    for section in SECTIONS:
        for pno in range(1, 41):
            page = decode_html(http_get(_list_url(section, pno), timeout=60))
            items = re.findall(
                r'href="(/page/%s/\d+/\d+\.html)"[^>]*>\s*([^<]{4,90})\s*<' % section, page)
            for href, text in items:
                m = NEWS_TITLE_PAT.search(text)
                if not m or int(m.group(1)) != year:
                    continue
                if any(w in text for w in ("专科", "艺术", "体育", "综合评价")):
                    continue
                return {"notice": SITE + href}
            dates = re.findall(r'listTime">(\d{4})-(\d{2})-\d{2}', page)
            if dates and all((int(y), int(mo)) < (year, 6) for y, mo in dates):
                break
    raise ValueError(f"上海 {year} 考生高考成绩分布表在 02200/08000 栏目未找到")


def candidates(src: dict[str, str]) -> list[str]:
    """数据候选：已登记的 data 优先；否则从正文页按出现顺序试各个 PDF。

    正文页上普通类排第一，后面是艺术类/体育类/综合评价；万一顺序变了，
    靠 `parse_pdf` 的标题校验兜底，`parse()` 会继续试下一个。
    """
    if src.get("data"):
        return [src["data"]]
    page = decode_html(http_get(src["notice"], timeout=90))
    urls = [h if h.startswith("http") else SITE + h for h in PDF_LINK_PAT.findall(page)]
    if not urls:
        raise ValueError(f"上海正文页没有 PDF 附件: {src['notice']}")
    return urls


def source(year: int) -> dict[str, str]:
    return SOURCES.get(year) or discover(year)


def parse(year: int) -> dict:
    src = source(year)
    last_err: Exception | None = None
    for data_url in candidates(src):
        try:
            return _parse_one(year, src, data_url)
        except ValueError as e:          # 艺术类/体育类表标题不符 -> 换下一个候选
            last_err = e
            continue
    raise last_err or ValueError(f"上海 {year} 没有可用的数据候选")


def _parse_one(year: int, src: dict[str, str], data_url: str) -> dict:
    blob = http_get(data_url, timeout=180)
    if blob[:4] != b"%PDF":
        raise ValueError(f"上海 {year} 附件不是 PDF: {data_url}")
    rows, top_note, title, dropped = parse_pdf(blob)
    if dropped:
        raise ValueError(f"上海 {year} 有 {len(dropped)} 行未解析（拒收整份）："
                         f"{'；'.join(dropped[:3])}")
    if len(rows) < 100:
        raise ValueError(f"上海 {year} 只解析出 {len(rows)} 行，版式可能变了")
    validate_rows(rows)
    return {
        "meta": {
            "year": year, "province": PROVINCE, "data_source": "official",
            "source_url": src["notice"],
            "data_url": data_url,
            "subject_scheme": SCHEME,
            "columns": 3,
            "table_title": title,
            "coverage": COVERAGE.get(year, "未知"),
            "tracks": {"primary": "高考总分（官方表只印分数/人数/累计人数，未注明加分口径）"},
            "note": ("3+3 全市一张「综合」表；高分逐分（无 10 分档）；"
                     "2024 起官方只印「本科录取控制分数线上考生」，"
                     "表底以下没有位次，跨年比较位次前先看 coverage/score_floor"),
            "score_floor": rows[-1][0],
            "score_max": rows[0][0],
            "total": rows[-1][2],
            "attachment_sha256": sha256(blob),
            "fetched_at": now_iso(),
        },
        "subjects": {"综合": {"rows": rows, "top_note": top_note}},
    }
