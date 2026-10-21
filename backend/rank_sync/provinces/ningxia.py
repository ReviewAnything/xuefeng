"""宁夏：nxjyks.cn（宁夏教育考试院）「普通高考一分段统计表」。

形态：**每年一篇文章**，正文只挂 PDF 附件，没有任何表格层。普通类固定是前两份
（`[1]` 文史/历史、`[2]` 理工/物理），后面还挂 6–24 份艺术综合分、体育综合分——
`pick_files` 按「一分段 + 科目词」认、按 `艺术|体育|综合分` 挡。

PDF 版式是 31 省里第二特殊的一种：**整页横向并排 6–7 组，每组两列
``分数段 | 累计人数``**，同一个 y 上的各格分属**不同区段**（第 1 组从最高分往下跑完
才轮到第 2 组）。所以：

- 不能按 y 拼成一条序列，必须**组内自上而下、组间 x 递增**（列主序）；
- 组号 = 该行内「分数段/累计」对的第几个（从左数），末几行会缺右侧组——
  那正是末列的列尾，按对序号归组天然正确；
- 官方**不印本段人数**，只有累计；本段按相邻累计差反算（`meta.derived_seg=True`，
  源值另存 `subjects.*.cum`），与内蒙古同一口径。

三个跨年差异（都在同一个站的文件里）：
1. 2022–2024 是 **文理分科**（表名「文史类/理工类」，落盘映射为历史类/物理类
   并留痕 `subject_aliases`），2025 起 3+1+2（「历史组/物理组」）；
2. 2022–2025 的行标签写成 ``616分以上``（顶部是截断桶），2026 改成 ``624分``；
3. 2026 起 PDF 变多页（2 页），2022–2025 都是单页；2026 还**不印 0 人的分数段**
   （2022–2025 印，靠累计重复体现），漏掉的分段记进 `subjects.*.omitted_scores`，
   累计链照样接得上——不猜、不补。

续页没有标题、只有表头，所以标题从各页正文里找第一处含「一分段」的行；
找不到或与年份/科类对不上，整份拒收。
"""
from __future__ import annotations

import html as ht
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLineHorizontal

from ..common import http_get, http_get_html, now_iso, sha256, validate_rows

PROVINCE = "宁夏"
SITE = "https://www.nxjyks.cn"
CHANNEL = SITE + "/contents/PTGK/PTGK_PTGK/"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

_A = CHANNEL + "{y}/{m}/{aid}.html"
_F = CHANNEL + "{y}/{m}/{aid}.files/{fid}_{n}.pdf"


def _art(y: int, m: str, aid: str, fid: str) -> dict:
    """一年一条：文章页 + 两份普通类 PDF（`_1` 历史/文史、`_2` 物理/理工）。"""
    return {
        "notice": _A.format(y=y, m=m, aid=aid),
        "files": {
            "历史类": _F.format(y=y, m=m, aid=aid, fid=fid, n=1),
            "物理类": _F.format(y=y, m=m, aid=aid, fid=fid, n=2),
        },
        "labels": {
            "历史类": f"{y}年宁夏普通高考总分一分段统计表（文史类）",
            "物理类": f"{y}年宁夏普通高考总分一分段统计表（理工类）",
        },
    }


SOURCES = {
    2022: _art(2022, "06", "20220623151417000", "20220623115716349"),
    2023: _art(2023, "06", "20230623164446000", "20230623162816953"),
    2024: _art(2024, "06", "20240623152147000", "20240623143202341"),
    2025: {
        "notice": CHANNEL + "2025/06/20250625111758000.html",
        "files": {
            "历史类": CHANNEL + "2025/06/20250625111758000.files/20250625111737812_1.pdf",
            "物理类": CHANNEL + "2025/06/20250625111758000.files/20250625111737812_2.pdf",
        },
        "labels": {
            "历史类": "01-2025年宁夏普通高考考生成绩一分段表（历史组）",
            "物理类": "02-2025年宁夏普通高考考生成绩一分段表（物理组）",
        },
    },
    2026: {
        "notice": CHANNEL + "2026/06/20260625113231000.html",
        "files": {
            "历史类": CHANNEL + "2026/06/20260625113231000.files/20260625113127194_1.pdf",
            "物理类": CHANNEL + "2026/06/20260625113231000.files/20260625113127194_2.pdf",
        },
        "labels": {
            "历史类": "01.2026年普通高考考生成绩一分段表（历史组）",
            "物理类": "02.2026年普通高考考生成绩一分段表（物理组）",
        },
    },
}

# 五年齐全：2022–2026 都能在「普通高考」栏目里找到主表
KNOWN_GAPS: dict[int, str] = {}

ALIASES = {y: {"历史类": "文史类", "物理类": "理工类"} for y in (2022, 2023, 2024)}

AUX_PAT = re.compile(r"艺术|体育|综合分")
SUBJECT_WORDS = {"历史类": ("历史", "文史", "文科"), "物理类": ("物理", "理工", "理科")}

LBL_PAT = re.compile(r"^(\d{3})分(?:以上)?$")
NUM_PAT = re.compile(r"^\d+$")
TITLE_PAT = re.compile(r"\d{4}年.{0,12}一分段")
ROW_TOL = 3.0      # 同一行的 y 容差（行距 10.5pt / 15.7pt 两种版式）
SCORE_MIN, SCORE_MAX = 100, 750
MIN_ROWS = 50      # 单科类少于 50 行必然只读到半页


# ---------------------------------------------------------------------------
# 解析（纯函数）
# ---------------------------------------------------------------------------
def group_rows(lines: list[tuple[float, float, str]]) -> list[list[tuple[float, str]]]:
    """(x, y, text) -> 按 y 聚行（自上而下），行内按 x 升序。"""
    lines = sorted(lines, key=lambda r: (-r[1], r[0]))
    rows: list[list[tuple[float, str]]] = []
    cur: list[tuple[float, str]] = []
    cy: float | None = None
    for x, y, t in lines:
        if cy is None or abs(y - cy) <= ROW_TOL:
            cur.append((x, t))
            cy = y if cy is None else cy
        else:
            rows.append(cur)
            cur, cy = [(x, t)], y
    if cur:
        rows.append(cur)
    return rows


def row_pairs(cells: list[tuple[float, str]]) -> list[tuple[str, int]]:
    """一行内的单元格 -> [(分数标签, 累计人数)]，按 x 顺序。

    两列在版式里可能是一个文本框（``616分以上 54``）、也可能是两个
    （``580分以上`` + ``119``），统一按「标签后紧跟数字」配对；表头
    （``分数段 累计人数``）、页码（``第 2页``）这类不配对的词直接忽略。
    """
    toks: list[str] = []
    for _x, t in sorted(cells):
        toks.extend(t.split())
    out: list[tuple[str, int]] = []
    pend: str | None = None
    for t in toks:
        if LBL_PAT.match(t):
            pend = t
        elif NUM_PAT.match(t):
            if pend is not None:
                out.append((pend, int(t)))
                pend = None
    return out


def rows_from_lines(lines: list[tuple[float, float, str]]) -> dict:
    """单页版式 -> {pairs: [(分数标签, 累计)], groups, title}（列主序）。

    组号取「该行内第几个键值对」——末几行缺右侧列时，左起第 k 对仍是第 k 组。
    组内分数必须严格降序，否则说明列读错了，直接抛错（上层整份拒收）。
    """
    bands: dict[int, list[tuple[str, int]]] = {}
    for cells in group_rows(lines):
        for k, (label, cum) in enumerate(row_pairs(cells)):
            bands.setdefault(k, []).append((label, cum))
    pairs: list[tuple[str, int]] = []
    for k in sorted(bands):
        prev: int | None = None
        for label, cum in bands[k]:
            score = int(label[:3])
            if not (SCORE_MIN <= score <= SCORE_MAX):
                raise ValueError(f"分数越界: {label}")
            if prev is not None and score >= prev:
                raise ValueError(f"组 {k} 内分数非降序: {prev} -> {score}")
            prev = score
            pairs.append((label, cum))
    title = ""
    for cells in group_rows(lines):
        for _x, t in sorted(cells):
            if TITLE_PAT.search(t):
                title = re.sub(r"\s+", "", t)
                break
        if title:
            break
    return {"pairs": pairs, "groups": len(bands), "title": title}


def pages_of(blob: bytes) -> list[list[tuple[float, float, str]]]:
    """PDF 字节 -> 每页的 (x, y, text) 行集合。"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(blob)
        path = f.name
    try:
        out = []
        for page in extract_pages(path):
            lines = []
            for el in page:
                if isinstance(el, LTTextContainer):
                    for ln in el:
                        if isinstance(ln, LTTextLineHorizontal):
                            t = ln.get_text().strip()
                            if t:
                                lines.append((ln.x0, ln.y0, t))
            out.append(lines)
        return out
    finally:
        Path(path).unlink(missing_ok=True)


def derive_rows(pairs: list[tuple[int, int]], min_rows: int = MIN_ROWS) -> list[list[int]]:
    """[(分数, 累计)] -> 三列 rows（本段=相邻累计差，首行本段=累计）。

    与内蒙古同一口径，但宁夏多一道「累计可以为 0 差」的容忍：2022–2025 官方会把
    0 人的分数段也印出来（累计重复），2026 起直接不印。所以这里只拒收**下降**，
    差为 0 是合法的空档。行数下限用来挡「只读到半页」。
    """
    if not pairs:
        raise ValueError("宁夏 PDF 未解析出任何数据行")
    rows: list[list[int]] = []
    prev: int | None = None
    for score, cum in pairs:
        seg = cum if prev is None else cum - prev
        if seg < 0:
            raise ValueError(
                f"累计人数下降（{score} 分：{prev} -> {cum}），列读错了，整份拒收")
        rows.append([score, seg, cum])
        prev = cum
    if len(rows) < min_rows:
        raise ValueError(f"只解析出 {len(rows)} 行，疑似半页/漏页，拒收")
    validate_rows(rows)
    return rows


def parse_pdf(blob: bytes) -> dict:
    """整份 PDF -> 三列 rows（本段为派生值）+ 源值累计 + 统计。"""
    pairs: list[tuple[int, int]] = []
    labels: list[str] = []
    groups: list[int] = []
    title = ""
    pages = 0
    for lines in pages_of(blob):
        pages += 1
        got = rows_from_lines(lines)
        if not got["pairs"]:
            continue
        groups.append(got["groups"])
        title = title or got["title"]
        for label, cum in got["pairs"]:
            labels.append(label)
            pairs.append((int(label[:3]), cum))
    rows = derive_rows(pairs)
    seen = {r[0] for r in rows}
    return {
        "rows": rows,
        "cum": [c for _, c in pairs],
        "title": title,
        "pages": pages,
        "groups": groups,
        "truncated_top": labels[0].endswith("以上"),
        "omitted": [s for s in range(rows[0][0], rows[-1][0], -1) if s not in seen],
    }


def subject_of_label(label: str) -> str | None:
    for subj, words in SUBJECT_WORDS.items():
        if any(w in label for w in words):
            return subj
    return None


def title_ok(title: str, year: int, subj: str) -> bool:
    """表名守卫：必须是该年**普通高考**一分段表，且科目词落在该科类上。"""
    t = title.replace(" ", "")
    if AUX_PAT.search(t) or "一分段" not in t or "普通高考" not in t:
        return False
    if f"{year}年" not in t:
        return False
    return subject_of_label(t) == subj


# ---------------------------------------------------------------------------
# 发现
# ---------------------------------------------------------------------------
def _attachments(notice: str) -> list[tuple[str, str]]:
    """文章页 -> [(绝对 URL, 附件名)]（本站附件全是 PDF）。"""
    h = http_get_html(notice)
    out: list[tuple[str, str]] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+?\.pdf)"[^>]*>(.*?)</a>', h, re.S | re.I):
        label = ht.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        out.append((urljoin(notice, m.group(1)), re.sub(r"\s+", " ", label).strip()))
    if not out:
        raise ValueError(f"宁夏文章页无 PDF 附件: {notice}")
    return out


def pick_files(pairs: list[tuple[str, str]], year: int) -> dict[str, str]:
    """挑出普通类两份（纯函数）。

    2026 的附件名里没有「宁夏」二字，所以只认「普通高考 + 一分段 + 年份」；
    艺术/体育综合分表名里也带「历史组/物理组」，必须先按 `AUX_PAT` 挡掉。
    """
    out: dict[str, str] = {}
    for url, label in pairs:
        if AUX_PAT.search(label):
            continue
        if "一分段" not in label or "普通高考" not in label or f"{year}年" not in label:
            continue
        subj = subject_of_label(label)
        if subj and subj not in out:
            out[subj] = url
    missing = [s for s in SUBJECTS if s not in out]
    if missing:
        raise ValueError(f"宁夏 {year} 文章页缺普通类附件：{missing}")
    return out


def parse_list(html: str) -> list[tuple[str, str, str]]:
    """栏目列表页 -> [(相对 URL, 标题, 日期)]。"""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        m = re.search(r'<a[^>]+href="([^"]*/\d{4}/\d{2}/\d+\.html)"[^>]*>(.*?)</a>',
                      tr, re.S | re.I)
        if not m:
            continue
        title = re.sub(r"\s+", " ", ht.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
        d = re.search(r"<span>(\d{4}-\d{2}-\d{2})</span>", tr)
        out.append((m.group(1), title, d.group(1) if d else ""))
    return out


LIST_MAX_PAGES = 70


def iter_listing():
    """翻「普通高考」栏目：index.html 是第 1 页，index_2.html 是第 2 页…

    注意没有 index_1.html（第 1 页就叫 index.html），别照着数页号。
    """
    for i in range(1, LIST_MAX_PAGES + 1):
        url = CHANNEL + ("index.html" if i == 1 else f"index_{i}.html")
        try:
            h = http_get_html(url)
        except Exception:      # noqa: BLE001 - 翻到头就是 404
            return
        got = parse_list(h)
        if not got:
            return
        for href, title, date in got:
            yield urljoin(url, href), title, date


def discover(year: int) -> dict:
    """翻栏目列表找该年主表文章，再回填附件。新增年份时用它校正 SOURCES。

    列表按日期倒序，翻到比目标年更早的条目就停——2022 要翻约 50 页，
    所以这个函数只在核对/补年时跑，日常同步直接走 SOURCES。
    """
    for url, title, date in iter_listing():
        if date and date[:4].isdigit() and int(date[:4]) < year:
            break
        if f"{year}年" not in title or "一分段" not in title:
            continue
        if AUX_PAT.search(title) or "普通高考" not in title:
            continue
        return {"notice": url, "files": pick_files(_attachments(url), year)}
    raise ValueError(f"宁夏 {year} 普通高考一分段统计表文章未找到")


def source(year: int) -> dict:
    return SOURCES.get(year) or discover(year)


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------
def parse(year: int) -> dict:
    src = source(year)
    files = dict(src.get("files") or pick_files(_attachments(src["notice"]), year))
    subjects: dict = {}
    shas: dict[str, str] = {}
    urls: dict[str, str] = {}
    for subj in SUBJECTS:
        url = files.get(subj)
        if not url:
            raise ValueError(f"宁夏 {year} 缺 {subj} 的附件")
        blob = http_get(url, timeout=180)
        got = parse_pdf(blob)
        if not title_ok(got["title"], year, subj):
            raise ValueError(
                f"宁夏 {year} {subj} 附件不是普通类一分段表"
                f"（表名：{got['title']!r}），拒收")
        rows = got["rows"]
        subjects[subj] = {
            "rows": rows,
            "cum": got["cum"],
            "top_note": f"{rows[0][0]}分以上" if got["truncated_top"] else "",
            "total": rows[-1][2],
            "score_floor": rows[-1][0],
            "omitted_scores": got["omitted"],
            "table_title": got["title"],
            "pdf_pages": got["pages"],
        }
        shas[subj], urls[subj] = sha256(blob), url
    floors = {s: v["score_floor"] for s, v in subjects.items()}
    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": urls.get("物理类", ""),
        "source_url_map": urls,
        "notice_url": src["notice"],
        "attachment_url_map": urls,
        "attachment_sha256_map": shas,
        "attachment_sha256": shas.get("物理类", ""),
        "attachment_label_map": dict(src.get("labels") or {}),
        "subject_scheme": "文理分科" if year <= 2024 else SCHEME,
        "columns": 3,
        "source_columns": 2,
        "layout": "并排多组（每页 6–7 组 × 两列），列主序读：组内自上而下、组间 x 递增",
        "derived_seg": True,
        "derived_seg_note": ("官方只印「分数段 | 累计人数」两列；本段=相邻累计差，"
                             "首行本段=累计（顶部是「X分以上」截断桶）；"
                             "累计列为源表原值，另存 subjects.*.cum 供核对"),
        "tracks": {"primary": "文化总分（官方未分加分轨）"},
        "coverage": ("普通类（首选科目历史/物理）全部考生；不含艺术类、体育类"
                     "（另有「艺术综合分/体育综合分一分段表」附件，本模块不取）"),
        "score_floor": floors,
        "omitted_note": ("官方不印 0 人的分数段（2022–2025 会印成累计重复行，"
                         "2026 起直接跳过），漏掉的分段记在 omitted_scores，累计链接得上"),
        "per_subject_note": {s: v["table_title"] for s, v in subjects.items()},
        "pdf_pages": {s: v["pdf_pages"] for s, v in subjects.items()},
        "fetched_at": now_iso(),
    }
    floor_note = {s: f"官方表止于 {v} 分，更低分数段未印" for s, v in floors.items() if v > 150}
    if floor_note:
        meta["score_floor_note"] = floor_note
    if year in ALIASES:
        meta["subject_aliases"] = ALIASES[year]
    if year in KNOWN_GAPS:
        meta["known_gap"] = KNOWN_GAPS[year]
    return {"meta": meta, "subjects": subjects}
