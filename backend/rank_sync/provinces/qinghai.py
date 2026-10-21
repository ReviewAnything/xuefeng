"""青海：qhjyks.com（青海省教育招生考试院）「排序成绩一分一段统计表」。

形态：**一年一篇文章挂 8 份 PDF**（普通类 / 艺考类 / 体育类 / 国家专项 / 省外民族班 /
省内预科 / 藏文 / 蒙文），普通类固定是第 1 份。与其它省不同，**一份 PDF 里同时含
物理组和历史组**（前半本历史、后半本物理，页脚写「第 N 页，共 22 页」），所以
一次下载拆两个科类。

PDF 版式是本省最规整的一种：**五列逐行** ``科类名称 | 投档分类型 | 总分 | 人数 | 累计数``，
每行都把科类与投档分类型重复印一遍。所以：
- 不用反算——**本段人数与累计数都是源表原值**，`validate_rows` 能真正校验
  「累计 = 前项 + 本段」；
- 顶部截断桶印成 ``≥625``（不是 ``625分以上``），首行按「累计 ≥ 本段」放宽；
- 表底会印到个位数分（2026 到 5 分），所以分数正则必须吃 **1–3 位**，
  不能照抄别省的 ``\\d{3}``。

口径注意：标题写明「表中总分已含政策性加分分值」，且列里有「投档分类型」——
这是**投档排序分**（含加分），与「文化总分」不是一回事，`meta.tracks` 里留痕。

改版事实（2022–2025 缺口的根因）：站点 2026 年整体换过 CMS。旧树
``/ztzl/ptgkz/`` 里 107 条现存条目（2022-05 起）**没有一条是一分一段**，
按 ID 探测也是 404；站内检索（``POST /cms/search/searchResults.jsp``）只索引到 2026。
阳光高考有 2025 镜像但 412 反爬，按纪律不拿第三方转录冒充 official。
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import html as ht

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLineHorizontal

from ..common import http_get, http_get_html, now_iso, sha256, validate_rows

PROVINCE = "青海"
SITE = "https://www.qhjyks.com"
COLUMN = SITE + "/zyym/szzkdtq/2022gkdt/"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

SOURCES = {
    2026: {
        "notice": COLUMN + "5826.htm",
        "files": {"普通类": SITE + "/docs/20260625110554854328.pdf"},
        "labels": {"普通类": "1.2026年青海省普通高校招生考试排序成绩一分一段统计表（普通类）"},
    },
}

KNOWN_GAPS = {
    2022: "站点 2026 年改版：旧树 /ztzl/ptgkz/ 现存 107 条（2022-05 起）无一分一段，"
          "按 ID 探测 404；站内检索只索引到 2026——官方原表已不可取，不拿第三方转录充 official",
    2023: "同上（旧 CMS 栏目已清理，站内检索无该年条目）",
    2024: "同上（旧 CMS 栏目已清理，站内检索无该年条目）",
    2025: "同上（阳光高考有同文镜像但 412 反爬，按纪律不采用）",
}

# 表内科类名 -> 落盘科类
GROUPS = {"物理组": "物理类", "历史组": "历史类"}
AUX_PAT = re.compile(r"艺考|艺术|体育|专项|民族|藏文|蒙文|预科")
ROW_TOL = 3.0
TOTAL_PAT = re.compile(r"^≥?(\d{1,3})$")
ROW_KEYS = ("科类名称", "总分", "人数", "累计数")
MIN_ROWS = 50


# ---------------------------------------------------------------------------
# 解析（纯函数）
# ---------------------------------------------------------------------------
def parse_rows(lines: list[tuple[float, float, str]]) -> dict[str, list[dict]]:
    """一页的 (x, y, text) -> {科类名: [{score, seg, cum, top}]}（页内自上而下）。

    五列顺序固定（科类 | 投档分类型 | 总分 | 人数 | 累计数），表头、导出注、
    页脚都不满足「首列是科类名」，自然被跳过。
    """
    rows: list[list[tuple[float, str]]] = []
    cur: list[tuple[float, str]] = []
    cy: float | None = None
    for x, y, t in sorted(lines, key=lambda r: (-r[1], r[0])):
        if cy is None or abs(y - cy) <= ROW_TOL:
            cur.append((x, t))
            cy = y if cy is None else cy
        else:
            rows.append(cur)
            cur, cy = [(x, t)], y
    if cur:
        rows.append(cur)

    out: dict[str, list[dict]] = {}
    for cells in rows:
        cells = sorted(cells)
        toks = [t for _x, t in cells]
        if len(toks) < 4 or toks[0] not in GROUPS:
            continue
        # 五列：科类 | 投档分类型 | 总分 | 人数 | 累计数
        if len(toks) != 5:
            raise ValueError(f"青海数据行列数不是 5：{toks}")
        label = toks[2].replace(" ", "")
        m = TOTAL_PAT.match(label)
        if not m:
            raise ValueError(f"青海总分列无法识别：{label!r}")
        try:
            seg, cum = int(toks[3]), int(toks[4])
        except ValueError as exc:
            raise ValueError(f"青海人数/累计列无法识别：{toks}") from exc
        out.setdefault(toks[0], []).append(
            {"score": int(m.group(1)), "seg": seg, "cum": cum, "top": label.startswith("≥")})
    return out


def pages_of(blob: bytes) -> list[list[tuple[float, float, str]]]:
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


def parse_pdf(blob: bytes) -> dict:
    """一份 PDF -> {subjects: {科类: {rows, top_note, total, score_floor}}, title, pages}。"""
    collected: dict[str, list[dict]] = {}
    title = ""
    pages = 0
    for lines in pages_of(blob):
        pages += 1
        if not title:
            for _x, _y, t in lines:
                if "一分一段" in t and "年" in t:
                    title = re.sub(r"\s+", "", t)
                    break
        for group, items in parse_rows(lines).items():
            collected.setdefault(group, []).extend(items)
    if not collected:
        raise ValueError("青海 PDF 未解析出任何数据行")

    subjects: dict[str, dict] = {}
    for group, items in collected.items():
        subj = GROUPS[group]
        rows = [[it["score"], it["seg"], it["cum"]] for it in items]
        if len(rows) < MIN_ROWS:
            raise ValueError(f"青海 {subj} 只解析出 {len(rows)} 行，疑似漏页，拒收")
        validate_rows(rows)
        subjects[subj] = {
            "rows": rows,
            "top_note": (f"{rows[0][0]}分以上" if items[0]["top"] else ""),
            "total": rows[-1][2],
            "score_floor": rows[-1][0],
        }
    missing = [s for s in SUBJECTS if s not in subjects]
    if missing:
        raise ValueError(f"青海 PDF 缺科类：{missing}")
    return {"subjects": subjects, "title": title, "pages": pages}


def title_ok(title: str, year: int) -> bool:
    """表名守卫：``{年}年青海省普通高校招生考试排序成绩一分一段统计表``（普通类那份）。

    同一篇文章挂的艺考/体育/专项/民族语言/预科 PDF 表名只差一个括号后缀，
    所以先按 `AUX_PAT` 挡掉，再认年份与「排序成绩一分一段统计表」。
    """
    t = title.replace(" ", "")
    if AUX_PAT.search(t):
        return False
    return (f"{year}年" in t and "青海省" in t
            and "普通高校招生考试" in t and "排序成绩一分一段统计表" in t)


# ---------------------------------------------------------------------------
# 发现
# ---------------------------------------------------------------------------
def _attachments(notice: str) -> list[tuple[str, str]]:
    h = http_get_html(notice)
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]+?\.pdf)"[^>]*>(.*?)</a>', h, re.S | re.I):
        label = ht.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        out.append((urljoin(notice, m.group(1)), re.sub(r"\s+", " ", label).strip()))
    if not out:
        raise ValueError(f"青海文章页无 PDF 附件: {notice}")
    return out


def pick_files(pairs: list[tuple[str, str]], year: int) -> dict[str, str]:
    """8 份附件里挑「（普通类）」那一份（纯函数）。

    艺考/体育/专项/民族语言/预科都不带「普通类」，直接挡；
    正式名里必定有「普通类），且年份要对得上。
    """
    for url, label in pairs:
        if AUX_PAT.search(label):
            continue
        if "（普通类）" not in label and "(普通类)" not in label:
            continue
        if f"{year}年" not in label or "一分一段" not in label:
            continue
        return {"普通类": url}
    raise ValueError(f"青海 {year} 文章页缺（普通类）附件")


def source(year: int) -> dict:
    if year in SOURCES:
        return SOURCES[year]
    raise ValueError(KNOWN_GAPS.get(year) or f"青海 {year} 未登记来源")


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------
def parse(year: int) -> dict:
    src = source(year)
    url = src["files"]["普通类"]
    blob = http_get(url, timeout=180)
    got = parse_pdf(blob)
    if not title_ok(got["title"], year):
        raise ValueError(f"青海 {year} 附件不是普通类一分一段表（表名：{got['title']!r}），拒收")
    digest = sha256(blob)
    subjects = {
        subj: {**blk,
               "table_title": got["title"],
               "pdf_pages": got["pages"]}
        for subj, blk in got["subjects"].items()
    }
    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": url,
        "source_url_map": {s: url for s in subjects},
        "notice_url": src["notice"],
        "attachment_url": url,
        "attachment_sha256": digest,
        "attachment_sha256_map": {s: digest for s in subjects},
        "attachment_label_map": dict(src.get("labels") or {}),
        "subject_scheme": SCHEME,
        "columns": 3,
        "source_columns": 5,
        "layout": "五列逐行「科类名称|投档分类型|总分|人数|累计数」，一份 PDF 前半本历史组、后半本物理组",
        "tracks": {"primary": "普通类投档成绩（表头注「总分已含政策性加分分值」）"},
        "caption": "注：表中总分已含政策性加分分值",
        "coverage": ("普通类（首选科目物理/历史）全部考生；艺考类、体育类、国家专项、"
                     "民族班/预科、藏文/蒙文各另有附件，本模块不取"),
        "score_floor": {s: v["score_floor"] for s, v in subjects.items()},
        "per_subject_note": {s: v["table_title"] for s, v in subjects.items()},
        "pdf_pages": {s: v["pdf_pages"] for s, v in subjects.items()},
        "fetched_at": now_iso(),
    }
    if year in KNOWN_GAPS:
        meta["known_gap"] = KNOWN_GAPS[year]
    return {"meta": meta, "subjects": subjects}
