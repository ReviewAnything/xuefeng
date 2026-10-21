"""北京：bjeea.cn「高考考生分数分布」（3+3，全市一张表），2022–2026 五年。

形态跨年变过两种，模块都要吃：
- 2022–2024：正文页直接是 HTML 表（``/html/gkgz/fujian/{year}/0625/<id>.html``），
  单元格里用 ``&rarr;`` 表示区间（``120→129``），必须 ``html.unescape`` 后再匹配；
- 2025–2026：正文页只挂 PDF 附件（``/uploads/soft/<yymmdd>/<file>.pdf``），
  文本层可用，10 页左右，页脚有「第 N 页，共 M 页」。

口径（官方表自带，别臆造）：
- 北京是 **3+3，全市一张「综合」表**，不分物理类/历史类，所以 ``SUBJECTS = ["综合"]``；
- 顶部 ``700以上`` / ``698分以上`` 是截断桶（只统计到该分之上的人数），打 ``top_note``；
- **高分逐分、低分按 10 分一档**：2026 逐分段止于 380，之后是 ``370→379``…``100→109``
  共 28 个 10 分档。10 分档不是某个具体分数，混进 ``rows`` 会让位次失真，
  因此单列 ``subjects.*.buckets``（``[low, high, seg, cum]``），并且校验它与
  ``rows`` 的累计链衔接（``首档累计 = 末行累计 + 首档人数``）；
- 表尾注「统计中的分数含全国性（照顾）加分」——这就是投档位次口径，记进 ``meta.tracks``；
- **7 月另发的「专科考生分数分布」是另一个口径**（只含未被本科录取的考生），
  绝不能并入本表，模块不取。
"""
from __future__ import annotations

import html as _html
import re

from ..common import decode_html, http_get, now_iso, sha256, validate_rows

PROVINCE = "北京"
SITE = "https://www.bjeea.cn"
SCHEME = "3+3"
SUBJECTS = ["综合"]
STATUS = "ready"

# 每年：正文页（可点开源溯）+ 数据页（HTML 表或 PDF）
SOURCES = {
    2022: {"notice": SITE + "/html/gkgz/tzgg/2022/0625/82075.html",
           "data": SITE + "/html/gkgz/fujian/2022/0625/82074.html"},
    2023: {"notice": SITE + "/html/gkgz/tzgg/2023/0625/83920.html",
           "data": SITE + "/html/gkgz/fujian/2023/0625/83922.html"},
    2024: {"notice": SITE + "/html/gkgz/tzgg/2024/0624/85430.html",
           "data": SITE + "/html/gkgz/fujian/2024/0625/85432.html"},
    2025: {"notice": SITE + "/html/gkgz/tzgg/2025/0625/87165.html",
           "data": SITE + "/uploads/soft/250625/172-2506250Q456.pdf"},
    2026: {"notice": SITE + "/html/gkgz/tzgg/2026/0624/88238.html",
           "data": SITE + "/uploads/soft/260625/2026年北京市高考考生分数分布.pdf"},
}

# 当前年份列表页（新年度发现用）：标题形如「北京市2027年高考考生分数分布」
LIST_URL = SITE + "/html/gkgz/tzgg/index.html"
TITLE_PAT = re.compile(r"(20\d{2})年.*高考考生分数分布")
PDF_LINK_PAT = re.compile(r'href="([^"]+\.pdf)"', re.I)
HEAD_WORDS = ("分数", "本段人数", "累计人数")
TOP_PAT = re.compile(r"^(\d{3})(?:分以上|以上)$")
SCORE_PAT = re.compile(r"^(\d{3})$")
BUCKET_PAT = re.compile(r"^(\d{2,3})\s*[-–—→]+\s*(\d{2,3})$")
NOTE_PAT = re.compile(r"^(注[:：]|说明)")
FOOTER_PAT = re.compile(r"^第\s*\d+\s*页")


def _cells(row_html: str) -> list[str]:
    return [_html.unescape(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row_html, re.I)]


def _classify(head: str, seg: str, cum: str, rows: list, buckets: list,
              dropped: list) -> None:
    """把一行三格分派到 rows / buckets，落不进去就进 dropped。"""
    if not (seg.isdigit() and cum.isdigit()):
        dropped.append(f"{head} | {seg} | {cum}")
        return
    mb = BUCKET_PAT.match(head)
    if mb:
        low, high = int(mb.group(1)), int(mb.group(2))
        if low > high:
            low, high = high, low
        buckets.append([low, high, int(seg), int(cum)])
        return
    mt = TOP_PAT.match(head)
    if mt:
        rows.append([int(mt.group(1)), int(seg), int(cum)])
        return
    ms = SCORE_PAT.match(head)
    if ms:
        rows.append([int(ms.group(1)), int(seg), int(cum)])
        return
    dropped.append(f"{head} | {seg} | {cum}")


def _order(rows: list[list[int]], buckets: list[list[int]]) -> None:
    rows.sort(key=lambda r: -r[0])
    buckets.sort(key=lambda b: -b[1])


def parse_html(page: str) -> tuple[list[list[int]], list[list[int]], str, list[str]]:
    """HTML 表 -> (rows, buckets, top_note, dropped)。"""
    rows: list[list[int]] = []
    buckets: list[list[int]] = []
    dropped: list[str] = []
    top_note = ""
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", page, re.I):
        cells = _cells(tr)
        if len(cells) != 3:
            # 标题行 / 表头 / 表尾注：只接受「注：…」这类说明，其余三格以外的行一律记未解析
            if cells and any(w in cells[0] for w in HEAD_WORDS):
                continue
            if cells and (NOTE_PAT.match(cells[0]) or "分数分布" in cells[0]):
                continue
            if any(cells):
                dropped.append(" | ".join(cells))
            continue
        head, seg, cum = cells
        if head in HEAD_WORDS or any(w in head for w in HEAD_WORDS):
            continue
        _classify(head, seg, cum, rows, buckets, dropped)
    _order(rows, buckets)
    if rows and rows[0][1] == rows[0][2]:
        top_note = f"{rows[0][0]}↑"  # 顶部截断桶：累计=本段
    return rows, buckets, top_note, dropped


def parse_pdf(blob: bytes) -> tuple[list[list[int]], list[list[int]], str, list[str]]:
    """PDF（10 页左右，每页 3 列 分数|本段人数|累计人数）-> 同 parse_html。"""
    import tempfile
    from pathlib import Path

    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer, LTTextLineHorizontal

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(blob)
        path = f.name
    rows: list[list[int]] = []
    buckets: list[list[int]] = []
    dropped: list[str] = []
    title = ""
    try:
        for page in extract_pages(path):
            lines = []
            for el in page:
                if isinstance(el, LTTextContainer):
                    for ln in el:
                        if isinstance(ln, LTTextLineHorizontal):
                            t = ln.get_text().strip()
                            if t:
                                lines.append((round(ln.y0, 1), (ln.x0 + ln.x1) / 2, t))
            if not title:
                # 表名在首页最上方（「北京市2026年高考考生分数分布」）
                cand = [t for _y, _x, t in lines if "分数分布" in t]
                title = cand[0] if cand else ""
            heads = [y for y, _x, t in lines if t in HEAD_WORDS]
            if len(heads) != 3:
                continue  # 无表头页（封面/说明）
            head_y = max(heads)
            data = [(y, xc, t) for y, xc, t in lines
                    if y < head_y - 4 and not FOOTER_PAT.match(t)]
            data.sort(key=lambda r: -r[0])
            groups: list[list[tuple[float, float, str]]] = []
            for rec in data:
                if groups and abs(rec[0] - groups[-1][0][0]) <= 3:
                    groups[-1].append(rec)
                else:
                    groups.append([rec])
            for g in groups:
                if len(g) != 3:
                    for _y, _x, t in g:
                        if not NOTE_PAT.match(t):
                            dropped.append(t)
                    continue
                head, seg, cum = [c[2] for c in sorted(g, key=lambda c: c[1])]
                _classify(head, seg, cum, rows, buckets, dropped)
    finally:
        Path(path).unlink(missing_ok=True)
    _order(rows, buckets)
    if not title.endswith("高考考生分数分布"):
        raise ValueError(f"北京 PDF 不是「高考考生分数分布」表（标题：{title!r}），拒收")
    top_note = f"{rows[0][0]}↑" if rows[0][1] == rows[0][2] else ""
    return rows, buckets, top_note, dropped


def _check_buckets(rows: list[list[int]], buckets: list[list[int]]) -> None:
    """10 分档的累计链必须接在逐分表末尾，且档内 seg=cum 递增自洽。"""
    prev = rows[-1][2]
    for low, high, seg, cum in buckets:
        if cum != prev + seg:
            raise ValueError(f"北京 10 分档累计断裂 {high}→{low}: {prev}+{seg}!={cum}")
        prev = cum


def discover(year: int) -> dict[str, str]:
    """在「通知公告」首页找该年的分数分布条目（新年度免改代码）。"""
    page = decode_html(http_get(LIST_URL, timeout=60))
    for href, text in re.findall(r'href="([^"]+)"[^>]*>\s*([^<]{4,60})\s*</a>', page):
        m = TITLE_PAT.search(text)
        if m and int(m.group(1)) == year and "专科" not in text:
            url = href if href.startswith("http") else SITE + href
            return {"notice": url}
    raise ValueError(f"北京 {year} 高考考生分数分布在通知公告首页未找到")


def candidates(src: dict[str, str]) -> list[str]:
    """数据候选：已登记的 data 优先；否则从正文页里找 HTML 表或 PDF 附件。

    正文页常同时挂「高考考生分数分布」与「单考考生分数分布」两个 PDF，
    文件名看不出区别，只能逐个下载、按 PDF 内首页标题筛（parse_pdf 里做校验）。
    """
    if src.get("data"):
        return [src["data"]]
    page = decode_html(http_get(src["notice"], timeout=90))
    if page.count("<tr") > 50:
        return [src["notice"]]
    urls = [h if h.startswith("http") else SITE + h for h in PDF_LINK_PAT.findall(page)]
    if not urls:
        raise ValueError(f"北京正文页既无表格也无 PDF 附件: {src['notice']}")
    return urls


def source(year: int) -> dict[str, str]:
    return SOURCES.get(year) or discover(year)


def parse(year: int) -> dict:
    src = source(year)
    last_err: Exception | None = None
    for data_url in candidates(src):
        try:
            return _parse_one(year, src, data_url)
        except ValueError as e:      # PDF 标题不符（单考/专科表）时换下一个候选
            last_err = e
            continue
    raise last_err or ValueError(f"北京 {year} 没有可用的数据候选")


def _parse_one(year: int, src: dict[str, str], data_url: str) -> dict:
    blob = http_get(data_url, timeout=120)
    is_pdf = blob[:4] == b"%PDF"
    if is_pdf:
        rows, buckets, top_note, dropped = parse_pdf(blob)
    else:
        rows, buckets, top_note, dropped = parse_html(decode_html(blob))
    if dropped:
        raise ValueError(f"北京 {year} 有 {len(dropped)} 行未解析（拒收整份）："
                         f"{'；'.join(dropped[:3])}")
    if len(rows) < 100:
        raise ValueError(f"北京 {year} 只解析出 {len(rows)} 行，版式可能变了")
    validate_rows(rows)
    if buckets:
        _check_buckets(rows, buckets)
    subj = {"rows": rows, "top_note": top_note}
    if buckets:
        subj["buckets"] = [{"range": [lo, hi], "seg": seg, "cum": cum}
                           for lo, hi, seg, cum in buckets]
    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": src["notice"],
        "data_url": data_url,
        "subject_scheme": SCHEME,
        "columns": 3,
        "tracks": {"primary": "含全国性照顾加分（表尾注：统计中的分数含全国性加分）"},
        "note": ("3+3 全市一张「综合」表；高分逐分、低分按 10 分一档，"
                 "10 分档单独存 buckets 不混进位次行；7 月另发的「专科考生分数分布」"
                 "是只含未被本科录取考生的另一口径，不并入"),
        "score_floor": rows[-1][0],
        "total": buckets[-1][3] if buckets else rows[-1][2],
        "fetched_at": now_iso(),
    }
    if is_pdf:
        meta["attachment_sha256"] = sha256(blob)
    else:
        meta["source_sha256"] = sha256(blob)
    return {"meta": meta, "subjects": {"综合": subj}}
