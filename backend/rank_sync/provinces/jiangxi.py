"""江西：jxeea.cn「普通高考一分一段表 / 分段表」（物理类、历史类各一份 PDF）。

版式最规矩的一类：单列、每页一整块 `分数 | 人数 | 累计人数`，首页顶部是表名，
每页顶部重复表名 + 表头，页脚「第 N 页，共 M 页」。

口径：
- **2022/2023 是文理分科**（PDF 里写「本科文史分段表」「文史类本科一分一段表」/
  「本科理工…」），落盘统一映射为 历史类/物理类 并在 `meta.subject_aliases` 留痕；
  2024 起才是 3+1+2（历史类/物理类）；
- 表体一直印到 100 分（全分数段），顶部 `640及以上` 是截断桶（人数=累计），打 `top_note`；
- 正文页同时挂「三校生一分一段表」（中职对口升学，另一套考生），**不并入本表**：
  靠 PDF 表名匹配 `(文史|理工|历史|物理)` 把三校生表挡住。
"""
from __future__ import annotations

import json
import re

import requests

from ..common import decode_html, http_get, now_iso, sha256, validate_rows

PROVINCE = "江西"
SITE = "https://www.jxeea.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

# 每年：公告页（可点开源溯）+ 两份 PDF（历史在前、物理在后——页面上的顺序就是这样）
SOURCES = {
    2022: {"notice": SITE + "/jxsjyksy/gsgg91/content/content_1855966846916169728.html",
           "pdfs": {"历史类": SITE + "/jxsjyksy/gsgg91/1855966846916169728/peBkLcnm.pdf",
                    "物理类": SITE + "/jxsjyksy/gsgg91/1855966846916169728/yZdKdheD.pdf"}},
    2023: {"notice": SITE + "/jxsjyksy/gsgg91/content/content_1856044140686938112.html",
           "pdfs": {"历史类": SITE + "/jxsjyksy/gsgg91/1856044140686938112/QImAkAgC.pdf",
                    "物理类": SITE + "/jxsjyksy/gsgg91/1856044140686938112/MldAC48U.pdf"}},
    2024: {"notice": SITE + "/jxsjyksy/gsgg91/content/content_1856091555406221312.html",
           "pdfs": {"历史类": SITE + "/jxsjyksy/gsgg91/1856091555406221312/2JEulIxD.pdf",
                    "物理类": SITE + "/jxsjyksy/gsgg91/1856091555406221312/lgaPMP53.pdf"}},
    2025: {"notice": SITE + "/jxsjyksy/gsgg91/content/content_1938096334352519168.html",
           "pdfs": {"历史类": SITE + "/jxsjyksy/gsgg91/1938096334352519168/WOn27m6u.pdf",
                    "物理类": SITE + "/jxsjyksy/gsgg91/1938096334352519168/7L9uupAh.pdf"}},
    2026: {"notice": SITE + "/jxsjyksy/gsgg91/content/content_2070077118825013248.html",
           "pdfs": {"历史类": SITE + "/jxsjyksy/gsgg91/2070077118825013248/xkO8FFcL.pdf",
                    "物理类": SITE + "/jxsjyksy/gsgg91/2070077118825013248/lKCJfQem.pdf"}},
}

# 2022/2023 官方仍是文理分科，落盘映射 + 留痕
ALIASES = {2022: {"历史类": "文史", "物理类": "理工"},
           2023: {"历史类": "文史", "物理类": "理工"}}

TITLE_PAT = re.compile(
    r"^(?:江西省)?20\d{2}年(?:江西省)?普通高考"
    r"(?:(?:本科)?(文史|理工)(?:类本科)?分段表"
    r"|(文史|理工)类本科一分一段表"
    r"|(历史|物理)类一分一段表)$")
THOUSANDS_PAT = re.compile(r"[\d,]+")

# 站内检索：`POST /queryList`（前端 jpage 的 proxyUrl），按标题关键字过滤
SEARCH_URL = SITE + "/queryList"
SEARCH_BASE = {"current": 1, "unitid": "309449", "webSiteCode": "jxsjyksy",
               "perPage": "20"}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _page_groups(page, tol: float = 3.0):
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


def is_noise(cells: list[str]) -> bool:
    """表名（每页重复）、表头、页脚都算版式噪声。"""
    joined = " ".join(cells)
    return ("分段表" in joined or "一分一段表" in joined
            or ("分数" in joined and "人数" in joined)
            or ("页" in joined and joined.strip().startswith("第")))


def row_of(cells: list[str]) -> list[int] | None:
    """一行 -> [分数, 人数, 累计]；表名/表头/页脚返回 None。"""
    if is_noise(cells):
        return None
    nums = [int(n.replace(",", "")) for c in cells for n in THOUSANDS_PAT.findall(c)]
    if len(nums) != 3:
        return None
    return nums


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
                joined = " ".join(cells)
                if not title and "段表" in joined:      # 「分段表」或「一分一段表」
                    title = joined
                row = row_of(cells)
                if row is None:
                    if not is_noise(cells) and any(c.strip() for c in cells):
                        dropped.append(joined)
                    continue
                rows.append(row)
    finally:
        Path(path).unlink(missing_ok=True)
    if not TITLE_PAT.match(title):
        raise ValueError(f"江西 PDF 不是「(文史|理工|历史|物理)分段表」（标题：{title!r}），拒收")
    if dropped:
        raise ValueError(f"江西 PDF 有 {len(dropped)} 行未解析（拒收整份）：{dropped[:3]}")
    if len(rows) < 200:
        raise ValueError(f"江西 PDF 只解析出 {len(rows)} 行，版式可能变了")
    rows.sort(key=lambda r: -r[0])
    validate_rows(rows)
    top_note = f"{rows[0][0]}↑" if rows[0][1] == rows[0][2] else ""
    return rows, top_note, title, dropped


def _subject_of_title(title: str) -> str:
    """文史/理工（2022–2023）与历史/物理（2024 起）都归到 历史类/物理类。"""
    return "历史类" if ("文史" in title or "历史" in title) else "物理类"


def discover(year: int) -> dict[str, str]:
    """站内检索找该年的分段表公告页：标题有两种写法（一分一段表 / 分段表）。

    同一篇文章常被同时投到「公示公告 gsgg91」与「通知公告 tzgg92」两个栏目，
    URL 不同、内容一致——优先取 gsgg91，与 SOURCES 里的登记口径保持一致。
    """
    found: list[str] = []
    for kw in ("一分一段表", "分段表"):
        resp = requests.post(SEARCH_URL, data={**SEARCH_BASE, "title": kw},
                             timeout=60, headers={"User-Agent": UA})
        data = (resp.json() or {}).get("data") or {}
        for hit in data.get("results") or []:
            src = hit.get("source") or {}
            title = src.get("title") or ""
            if str(year) not in title or "三校生" in title:
                continue
            try:
                url = (json.loads(src.get("urls") or "{}") or {}).get("pc")
            except ValueError:
                url = None
            if not url:
                continue
            full = url if url.startswith("http") else SITE + url
            if full not in found:
                found.append(full)
    if found:
        return {"notice": next((u for u in found if "/gsgg91/" in u), found[0])}
    raise ValueError(f"江西 {year} 一分一段表公告页未找到（已试「一分一段表」「分段表」）")


def source(year: int) -> dict:
    return SOURCES.get(year) or discover(year)


def _pdfs_from_notice(notice: str) -> dict[str, str]:
    page = decode_html(http_get(notice, timeout=90))
    urls: list[str] = []
    for h in re.findall(r'href="([^"]+\.pdf)"', page):
        full = h if h.startswith("http") else SITE + h
        if full not in urls:
            urls.append(full)
    if len(urls) < 2:
        raise ValueError(f"江西公告页 PDF 不足两份: {notice}")
    return {"历史类": urls[0], "物理类": urls[1]}


def parse(year: int) -> dict:
    src = source(year)
    files = dict(src.get("pdfs") or _pdfs_from_notice(src["notice"]))
    subjects: dict = {}
    shas: dict[str, str] = {}
    floors: dict[str, int] = {}
    urls: dict[str, str] = {}
    for subj in SUBJECTS:
        url = files.get(subj)
        if not url:
            raise ValueError(f"江西 {year} 缺 {subj} 的 PDF")
        blob = http_get(url, timeout=180)
        rows, top_note, title, _dropped = parse_pdf(blob)
        if _subject_of_title(title) != subj:
            raise ValueError(f"江西 {year} PDF 科类不符：期望 {subj}，标题 {title!r}")
        subjects[subj] = {"rows": rows, "top_note": top_note, "total": rows[-1][2],
                          "table_title": title}
        shas[subj] = sha256(blob)
        floors[subj] = rows[-1][0]
        urls[subj] = url
    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": src["notice"],
        "subject_scheme": "文理分科" if year <= 2023 else SCHEME,
        "columns": 3,
        "tracks": {"primary": "高考总分（含政策加分）"},
        "note": ("物理/历史各一份 PDF，单列三列；表体印到 100 分（全分数段）；"
                 "正文页另挂「三校生一分一段表」，是另一套考生，不并入"),
        "attachment_url_map": urls,
        "attachment_sha256_map": shas,
        "attachment_url": urls.get("物理类", ""),
        "attachment_sha256": shas.get("物理类", ""),
        "score_floor": floors,
        "fetched_at": now_iso(),
    }
    if year in ALIASES:
        meta["subject_aliases"] = ALIASES[year]
    return {"meta": meta, "subjects": subjects}
