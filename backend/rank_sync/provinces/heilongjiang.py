"""黑龙江：lzk.hl.cn（龙招港）「普通高考文化课一分段统计表」（每科类一份 xls）。

版式是最规矩的三列：`分段 | 段内人数 | 累计人数`，逐分一行。但四个年份四套写法：

- 顶行有 `677以上`（2022–2024）/ `694及以上`（2025–2026）两种写法，都是截断桶；
- **2025 的顶行段内人数印的是「上一分之上的人数」**（物理 `694及以上 | 3 | 34`、
  历史 `659及以上 | 3 | 19`），与自己的累计数矛盾；官方通稿与其它年份一致地写作
  `694-750 | 34 | 34`。所以顶行统一 `本段=累计`，源表印的值另存 `top_seg_printed`；
- 表尾 2025/2026 多一行 `129及以下 | 略 | (空)`——没有数字，是「以下略」标记，
  记进 `omitted_below`，不能当分数行；2022–2024 则直接止于 150/130；
- **0 人的分段不印**（2024 历史缺 673、2025 物理缺 136/134、2025 历史缺 654/144、
  2026 历史缺 664），累计链照样接得上，缺口记进 `omitted_scores`。

载体一直是 xls（2022/2023/2024 是 BIFF，2025/2026 是 xlsx 装 .xls），按魔数分派。

公告页分散在三个栏目：2022 在高考频道根目录 `/gkpd/`、2023 在**新闻公告 `/zkyw/`**、
2024–2026 在 `/gkpd/gkxx/`。所以 `SOURCES` 逐年登记，`discover()` 三个栏目都翻。
"""
from __future__ import annotations

import html as ht
import io
import re
from urllib.parse import urljoin

from ..common import http_get, http_get_html, now_iso, sha256, validate_rows

PROVINCE = "黑龙江"
SITE = "https://www.lzk.hl.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

SOURCES = {
    2022: {"notice": SITE + "/gkpd/202206/t20220624_18175.htm",
           "files": {"物理类": SITE + "/gkpd/202206/W020220628383159617332.xls",
                     "历史类": SITE + "/gkpd/202206/W020220628383159831524.xls"}},
    2023: {"notice": SITE + "/zkyw/202306/t20230624_18600.htm",
           "files": {"物理类": SITE + "/zkyw/202306/W020230624403795540111.xls",
                     "历史类": SITE + "/zkyw/202306/W020230624403796489060.xls"}},
    2024: {"notice": SITE + "/gkpd/gkxx/202406/t20240625_19065.htm",
           "files": {"物理类": SITE + "/gkpd/gkxx/202406/W020240625655570648865.xls",
                     "历史类": SITE + "/gkpd/gkxx/202406/W020240625655570559993.xls"}},
    2025: {"notice": SITE + "/gkpd/gkxx/202506/t20250624_19420.htm",
           "files": {"物理类": SITE + "/gkpd/gkxx/202506/W020250624501230928278.xls",
                     "历史类": SITE + "/gkpd/gkxx/202506/W020250624501230928960.xls"}},
    2026: {"notice": SITE + "/gkpd/gkxx/202606/t20260624_19820.htm",
           "files": {"物理类": SITE + "/gkpd/gkxx/202606/W020260624618521422685.xls",
                     "历史类": SITE + "/gkpd/gkxx/202606/W020260624618521321776.xls"}},
}

# 2022/2023 官方仍是文理分科，落盘映射 + 留痕
ALIASES = {2022: {"历史类": "文科", "物理类": "理科"},
           2023: {"历史类": "文科", "物理类": "理科"}}

# 附件名/表名：只要「文化课」的普通类，艺术/体育是另一套综合分表
AUX_PAT = re.compile(r"艺术|体育|综合分|对口|专升本")
TOP_PAT = re.compile(r"^(\d{3})\s*分?\s*(?:及以上|以上)$")
BELOW_PAT = re.compile(r"^(\d{3})\s*分?\s*(?:及以下|以下)$")
HEADER_WORDS = ("分段", "分数", "档分")


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _num(v) -> int | None:
    """单元格 -> 整数。兼容 float、'692'、带千分位；'略' 等非数字返回 None。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "")
    return int(s) if s.isdigit() else None


def _table_of_xls(blob: bytes) -> list[list]:
    """按魔数分派 BIFF / OOXML（2025 起附件叫 .xls 其实是 xlsx）。"""
    if blob[:2] == b"PK":
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True)
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    if blob[:4] == b"\xd0\xcf\x11\xe0":
        import xlrd

        sh = xlrd.open_workbook(file_contents=blob).sheet_by_index(0)
        return [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    raise ValueError(f"既不是 BIFF 也不是 OOXML（前 4 字节 {blob[:4]!r}）")


def parse_table(table: list[list]) -> dict:
    """二维表 -> {rows, title, top_note, top_seg_printed, omitted_below, omitted_scores}。

    ``rows`` 里分数严格降序、累计=前项+本段；顶行是截断桶（`本段=累计`）。
    """
    hdr = None
    for i, row in enumerate(table[:8]):
        first = str(row[0]).strip() if row else ""
        # 表头格必须**正好**是「分段/分数/档分」——标题行「…一分段统计表」也含「分段」，
        # 用包含判断会把标题行误当表头
        if first in HEADER_WORDS and len(row) >= 3 \
                and any("人数" in str(c) for c in row[1:3]):
            hdr = i
            break
    if hdr is None:
        raise ValueError("黑龙江 xls 未找到「分段 | 段内人数 | 累计人数」表头")
    title = ""
    for row in table[:hdr]:
        if row and str(row[0]).strip():
            title = str(row[0]).replace("\n", "").strip()
            break

    rows: list[list[int]] = []
    top_note = ""
    top_seg_printed: int | None = None
    omitted_below: dict | None = None
    for row in table[hdr + 1:]:
        if not row:
            continue
        label = str(row[0]).strip()
        seg, cum = (_num(row[1]) if len(row) > 1 else None,
                    _num(row[2]) if len(row) > 2 else None)
        m_top = TOP_PAT.match(label)
        if m_top:
            score = int(m_top.group(1))
            if seg is None or cum is None:
                raise ValueError(f"顶部截断桶缺数字：{label!r}")
            if seg != cum:
                # 2025 的生成器把「上一分之上的人数」印在段内列；官方通稿按 X-750 | 累计 | 累计
                top_seg_printed = seg
                seg = cum
            rows.append([score, seg, cum])
            top_note = f"{score}↑"
            continue
        m_below = BELOW_PAT.match(label)
        if m_below:
            omitted_below = {"score_below": int(m_below.group(1)),
                             "note": str(row[1]).strip() if len(row) > 1 else ""}
            continue
        score = _num(row[0])
        if score is None:
            continue
        if seg is None or cum is None:
            raise ValueError(f"分段行缺数字：{label!r}")
        rows.append([score, seg, cum])
    if not rows:
        raise ValueError("黑龙江 xls 未解析出任何数据行")
    validate_rows(rows)
    seen = {r[0] for r in rows}
    omitted = [s for s in range(rows[0][0], rows[-1][0], -1) if s not in seen]
    return {"rows": rows, "title": title, "top_note": top_note or f"{rows[0][0]}↑",
            "top_seg_printed": top_seg_printed,
            "omitted_below": omitted_below, "omitted_scores": omitted}


def parse_xls(blob: bytes) -> dict:
    return parse_table(_table_of_xls(blob))


# ---------------------------------------------------------------------------
# 发现 / 取数
# ---------------------------------------------------------------------------
def _subject_of_title(title: str) -> str:
    """理科/物理类 -> 物理类；文科/历史类 -> 历史类。"""
    if "文科" in title or "历史类" in title:
        return "历史类"
    if "理科" in title or "物理类" in title:
        return "物理类"
    raise ValueError(f"黑龙江表名无法判定科类：{title!r}")


def title_ok(title: str, year: int) -> bool:
    """表名守卫：必须是该年普通高考**文化课**一分段统计表（体育/艺术另有一套）。"""
    return (f"黑龙江省{year}年普通高考" in title.replace(" ", "")
            and "一分段统计表" in title and "文化课" in title
            and not AUX_PAT.search(title))


def _attachments(notice: str) -> list[tuple[str, str]]:
    h = http_get_html(notice)
    out: list[tuple[str, str]] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+\.(?:xls|xlsx))"[^>]*>(.*?)</a>',
                         h, re.S | re.I):
        label = re.sub(r"\s+", " ", ht.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
        out.append((urljoin(notice, m.group(1)), label))
    if not out:
        raise ValueError(f"黑龙江公告页无 xls 附件: {notice}")
    return out


def pick_files(pairs: list[tuple[str, str]], year: int) -> dict[str, str]:
    """挑出两份文化课附件（纯函数）。

    2022 一篇挂 22 个附件、2023 挂 24 个，除前两份外全是艺术/体育综合分表；
    艺术类那份名字里也带「文化课」（`理科艺术文化课成绩一分段表`），
    所以必须先按 `艺术|体育` 挡掉，再按科类关键词认。
    """
    out: dict[str, str] = {}
    keys = {"物理类": ("理科", "物理类"), "历史类": ("文科", "历史类")}
    for subj in SUBJECTS:
        for url, label in pairs:
            if AUX_PAT.search(label):
                continue
            if "文化课" not in label or "一分段" not in label:
                continue
            if not any(k in label for k in keys[subj]):
                continue
            out[subj] = url if url.startswith("http") else urljoin(SITE, url)
            break
    missing = [s for s in SUBJECTS if s not in out]
    if missing:
        raise ValueError(f"黑龙江 {year} 公告页缺附件：{missing}")
    return out


CHANNELS = ("/gkpd/gkxx/", "/gkpd/", "/zkyw/", "/gkpd/cjfb/")
_LIST_MAX_PAGES = 40


def _iter_channel(chan: str):
    """栏目列表翻页（静态站：index.htm / index_2.htm …，翻到 404 为止）。

    产出 ``(文章绝对 URL, URL 里的日期 YYYYMMDD, 标题)``。
    """
    for i in range(_LIST_MAX_PAGES):
        path = chan + ("index.htm" if i == 0 else f"index_{i + 1}.htm")
        page_url = SITE + path
        try:
            h = http_get_html(page_url)
        except Exception:      # noqa: BLE001 - 翻页到头就是 404
            return
        found = False
        for m in re.finditer(r'<a[^>]+href="([^"]*t(\d{8})_\d+\.htm)"[^>]*>(.*?)</a>',
                             h, re.S):
            found = True
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(3))).strip()
            yield urljoin(page_url, m.group(1)), m.group(2), title
        if not found:
            return


def discover(year: int) -> dict:
    """跨栏目翻列表找该年主表通告。

    黑龙江的发布栏目逐年漂：2022 在 `/gkpd/`、2023 在 `/zkyw/`（新闻公告）、
    2024 起在 `/gkpd/gkxx/`；只翻一个栏目必然漏年。日期在 URL 里（tYYYYMMDD），
    翻到比目标年更早的月份就换下一个栏目。
    """
    for chan in CHANNELS:
        for url, date, title in _iter_channel(chan):
            if date[:4].isdigit() and int(date[:4]) < year:
                break
            if str(year) not in title or "一分段统计表" not in title:
                continue
            if AUX_PAT.search(title) or "普通高考" not in title:
                continue
            return {"notice": url}
    raise ValueError(f"黑龙江 {year} 普通高考一分段统计表通告未找到")


def source(year: int) -> dict:
    return SOURCES.get(year) or discover(year)


def parse(year: int) -> dict:
    src = source(year)
    files = dict(src.get("files") or pick_files(_attachments(src["notice"]), year))
    subjects: dict = {}
    shas: dict[str, str] = {}
    urls: dict[str, str] = {}
    floors: dict[str, int] = {}
    for subj in SUBJECTS:
        url = files.get(subj)
        if not url:
            raise ValueError(f"黑龙江 {year} 缺 {subj} 的附件")
        blob = http_get(url, timeout=180)
        got = parse_xls(blob)
        title = got["title"]
        if not title_ok(title, year):
            raise ValueError(f"黑龙江 {year} 附件不是文化课一分段表（表名：{title!r}），拒收")
        if _subject_of_title(title) != subj:
            raise ValueError(f"黑龙江 {year} 科类不符：期望 {subj}，表名 {title!r}")
        rows = got["rows"]
        subjects[subj] = {
            "rows": rows,
            "top_note": got["top_note"],
            "total": rows[-1][2],
            "table_title": title,
            "omitted_scores": got["omitted_scores"],
        }
        if got["omitted_below"]:
            subjects[subj]["omitted_below"] = got["omitted_below"]
        if got["top_seg_printed"] is not None:
            # 源表顶行的段内人数与累计矛盾（2025 生成器的写法），留痕备查
            subjects[subj]["top_seg_printed"] = got["top_seg_printed"]
        shas[subj] = sha256(blob)
        urls[subj] = url
        floors[subj] = rows[-1][0]
    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": src["notice"],
        "subject_scheme": "文理分科" if year <= 2023 else SCHEME,
        "columns": 3,
        "tracks": {"primary": "高考文化课成绩（不含照顾政策分）"},
        "note": ("逐分一行的三列统计表；顶行 `X以上/X及以上` 是截断桶（2025 的顶行段内人数"
                 "印成了「上一分之上的人数」，统一按 `本段=累计`，源值另存 top_seg_printed）；"
                 "0 人分段不印，缺口记 omitted_scores；2025/2026 表尾 `N及以下 略` 记 "
                 "omitted_below；正文另挂艺术/体育综合分表，不并入"),
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
