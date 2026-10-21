"""安徽：jyt.ah.gov.cn / ahzsks.cn「考生成绩分档表（含加分）」，2022–2026 五年。

版式：**一份 PDF 装两个科类**（2022/2023 表头写 ``科类：文史/理工``，
2024 起写 ``历史科目组合/物理科目组合``），每页横向并排 3–5 组
``分数|人数|累计人数``，末页组数会少（2023 文史末页只有 3 组）。

因此不能按「整页一个 block」解析（浙江/湖北的做法），也不能按 y 拼行
（同一 y 上的多格属于不同分数段）。这里按列重组：**数据列右对齐**，
同列所有单元格的右边界 x1 恒定（与数字位数无关），把全页 x1 聚成 3N 个簇，
每 3 簇为一组（分数/人数/累计），簇号 //3 即组号、%3 即列号。

坑（都踩过）：
- 每页的 ``科类：…`` 行决定该页属于哪个科类，必须页级跟踪；
- 页面组数不固定（末页会少几组），不能按固定组数校验；
- 顶部首行是 ``637及以上``：只印合计人数，``人数`` 与 ``累计`` 同值；
- 表尾三种写法：2022 是带数字的末行桶 ``200及以下 | 17015 | 182811``
  （落 ``below_bucket``）；2023–2026 是 ``200以下略`` 截断说明
  （落 ``omitted_below``，下面不再逐分印）；
- 2025/2026 的 PDF 生成器不同：2026 把表头 ``人数 累计人数 分数`` 三格并成一段文本，
  所以**不能靠表头文字定位列**，只能靠数据自身聚类；
- **黏连行**（pdfminer 把同一基线上相邻两段文本并成一行）有两种语义：
  2025 ``'137403 200以下'`` = 累计数字 + 游离注释；2022/2023
  ``'162638 200及以下'`` / ``'144375200 以下'`` = 上一组累计 + 下一组分数格。
  拆分必须**懒惰匹配**（取最短累计位数）且分数首位非零；
- 同一行的单元格 y 可相差 0.3pt（124.4 vs 124.7），聚行必须用容差比较，
  不能用 ``round(y/tol)``（会把一行劈成两行、整行丢字段）；
- PDF 带「禁止文本提取」元数据：pdfminer 给 warning，但文本层真实，照常解析
  （不做 OCR，也不绕过任何加密）。
"""
from __future__ import annotations

import collections
import re
import statistics
import tempfile
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLineHorizontal

from ..common import http_get, now_iso, sha256, validate_rows

PROVINCE = "安徽"
SITE = "https://jyt.ah.gov.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

# 省教育厅「招生考试程序及结果」信息公开检索（分档表逐年的法定公开渠道）
SEARCH_URL = ("https://jyt.ah.gov.cn/site/search/6788021?keywords=%E6%88%90%E7%BB%A9%E5%88%86%E6%A1%A3%E8%A1%A8"
              "&fuzzySearch=true&sort=intelligent&orderType=0")
ENTRY_PAT = re.compile(r'【信息公开】</span>\s*<a '
                       r'href="(https://jyt\.ah\.gov\.cn/public/7071/(\d+)\.html)"'
                       r'[^>]*title="([^"]*分档表[^"]*)"')
PDF_PAT = re.compile(r'href="(/group3/[^"]+\.pdf)"')
YEAR_PAT = re.compile(r"(20\d{2})年")

# 已知年份的公告页与附件（discover() 可自动补全 2025 及以后的年份）
NOTICES = {
    2025: "https://jyt.ah.gov.cn/public/7071/40757398.html",
    2026: "https://jyt.ah.gov.cn/public/7071/40794044.html",
}
# 2022–2024：省教育厅信息公开栏目 2025-06 才建起来（二分探测确认单元下界
# 40757397 = 2025-06-25），老附件没有可定位的公告页；考试院官网的固定路径
# 原表文件本身即官方来源（URL 可点开、内容与官方通稿锚点逐项吻合）。
PDFS = {
    2022: "https://www.ahzsks.cn/an-hui-sheng-2022-kskscjfdb.pdf",
    2023: "https://www.ahzsks.cn/an-hui-sheng-2023-kskscjfdb.pdf",
    2024: "https://www.ahzsks.cn/an-hui-sheng-2024-kskscjfdb.pdf",
    2025: "https://www.ahzsks.cn/pic/file/20250625/20250625150831_928.pdf",
    2026: "https://jyt.ah.gov.cn/group3/M00/14/AF/wKg86mo-PZ2AGH87AAF5XhX1T7c640.pdf",
}

SUBJECT_OF_LABEL = {
    "历史科目组合": "历史类", "物理科目组合": "物理类",
    # 2022/2023 文理分科年份的官方表头写法，与 3+1+2 口径等价映射
    "文史": "历史类", "理工": "物理类",
}
ROW_TOL = 3.0
# 同一列右边界 x1 的聚簇容差（右对齐下实测离散度 < 1pt，列间距 ≥ 45pt）
CLUSTER_TOL = 3.0
SCORE_PAT = re.compile(r"^(\d{1,3})(?:分)?(?:及以上?)?$")
# 表尾截断说明（可能出现在分数列，也可能黏在累计列右侧）
SCORE_OMIT_PAT = re.compile(r"^(\d{1,3})\s*分?\s*(?:及)?以下")
# 「累计+分数」黏连行：``'144375200 以下'`` = 累计 144375 + 分数格 '200 以下'。
# 必须懒惰匹配（取最短的累计位数）且分数首位非零，否则会错拆成
# ``'14437520'`` + ``'0 以下'``（2023 版式实测踩过）。
NOTE_SPLIT_PAT = re.compile(r"^(\d+?)\s*([1-9]\d{0,2}\s*分?\s*(?:及)?以下)")
NOTE_ONLY_PAT = re.compile(r"^(?:略|以下|以下略|分以下略)$")
FOOTER_PAT = re.compile(r"^第\s*\d+\s*页")
HEAD_PAT = re.compile(r"分数")


def _page_lines(page) -> list[tuple[float, float, float, str]]:
    """返回 (x0, x1, y0, text)：x1 是列归属的依据（该表所有数字列右对齐）。"""
    out = []
    for el in page:
        if isinstance(el, LTTextContainer):
            for ln in el:
                if isinstance(ln, LTTextLineHorizontal):
                    t = ln.get_text().strip()
                    if t:
                        out.append((ln.x0, ln.x1, ln.y0, t))
    return out


def _digit_width(lines: list[tuple[float, float, float, str]]) -> float:
    """由纯数字单元格反推单个数字的宽度，用于把「数字+注释」黏连行拆回数字。"""
    widths = [(x1 - x0) / len(t) for x0, x1, _y, t in lines if t.isdigit() and len(t) >= 2]
    return statistics.median(widths) if widths else 5.0


def _clean_lines(lines: list[tuple[float, float, float, str]]
                 ) -> list[tuple[float, float, float, str]]:
    """去掉页脚与纯注释文本；把「数字+注释」黏连行拆成两个单元格。

    黏连行有两种，拆法相同但语义相反：
    - 2025：``'137403 200以下'`` = 累计列数字 + 右侧**游离注释**（表尾截断说明）；
    - 2022：``'162638 200及以下'`` = 上一组累计数字 + 下一组**分数列**的末行桶
      （pdfminer 把同一基线上相邻两段文本并成一行）。

    拆出的注释单元格保留整行右边界（x1 精确，聚类只认 x1），x0 只是估计值；
    它究竟是「游离注释」还是「分数格」，由 ``_parse_page`` 按能否落入某个列簇判定。
    """
    dw = _digit_width(lines)
    out: list[tuple[float, float, float, str]] = []
    for x0, x1, y, t in lines:
        if FOOTER_PAT.match(t) or NOTE_ONLY_PAT.match(t):
            continue
        m = NOTE_SPLIT_PAT.match(t)
        if m:
            digits, note = m.group(1), m.group(2)
            out.append((x0, x0 + dw * len(digits), y, digits))
            out.append((x0 + dw * (len(digits) + 0.6), x1, y, note))
            continue
        out.append((x0, x1, y, t))
    return out


def _column_anchors(cells: list[tuple[float, float, float, str]]) -> list[float]:
    """把全页 x1 聚成列簇（右对齐，同列恒定），返回簇中心升序。

    只统计「数据格」（纯数字或分数格，含 ``637及以上`` 这类截断桶写法）；
    ``200及以下`` 注释文本不参与聚类，否则末行桶会多造出一个列簇。
    """
    vals = sorted(x1 for _x0, x1, _y, t in cells
                  if t.isdigit() or SCORE_PAT.match(t))
    if not vals:
        raise ValueError("安徽分档表解析：该页没有数据单元格")
    clusters: list[list[float]] = [[vals[0]]]
    for v in vals[1:]:
        if v - clusters[-1][-1] <= CLUSTER_TOL:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    centers = [sum(c) / len(c) for c in clusters]
    if len(centers) % 3:
        raise ValueError(f"安徽分档表解析：列簇数 {len(centers)} 不是 3 的倍数"
                         f"（分数/人数/累计），版式可能变了")
    return centers


def _nearest(centers: list[float], x1: float, tol: float = 4.0) -> int | None:
    best, best_d = None, None
    for i, c in enumerate(centers):
        d = abs(x1 - c)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best if best_d is not None and best_d <= tol else None


def _group_rows(cells: list[tuple[float, float, float, str]]
                ) -> list[list[tuple[float, float, float, str]]]:
    """按 y 把单元格聚成视觉行（容差 ROW_TOL）。

    不能用 ``round(y / ROW_TOL)`` 分桶：2022 版式里同一行的单元格 y 可相差
    0.3pt（124.4 vs 124.7），跨容差边界时一行会被劈成两行、整行丢字段。
    """
    ordered = sorted(cells, key=lambda c: -c[2])
    rows: list[list[tuple[float, float, float, str]]] = []
    for c in ordered:
        if rows and abs(c[2] - rows[-1][0][2]) <= ROW_TOL:
            rows[-1].append(c)
        else:
            rows.append([c])
    return rows


def _parse_page(cells: list[tuple[float, float, float, str]]
                ) -> tuple[list[list[int]], list[dict], list[dict], list[str]]:
    """单页 → (行, 截断说明, 末行桶, 未解析文本)。

    ``未解析文本`` 非空即调用方必须整份拒收：静默丢行会让累计链看起来仍然自洽
    （陕西两位数被吞那次的教训）。
    """
    centers = _column_anchors(cells)
    buckets: dict[tuple[int, int], dict] = {}
    omits: list[dict] = []
    belows: list[dict] = []
    dropped: list[str] = []
    for ri, row_cells in enumerate(_group_rows(cells)):
        y = max(c[2] for c in row_cells)
        for x0, x1, _cy, t in row_cells:
            ci = _nearest(centers, x1)
            if ci is None:
                # 落不进任何列簇的「N 分以下」文本是表尾游离注释（2025 版式），
                # 落得进的就是分数格（2022 版式的末行桶），由行组装逻辑区分。
                mo = SCORE_OMIT_PAT.match(t)
                if mo:
                    omits.append({"score_below": int(mo.group(1)), "omitted": True})
                    continue
                dropped.append(f"{t}(x1={x1:.1f})")
                continue
            blk, col = divmod(ci, 3)
            slot = buckets.setdefault((blk, ri), {"y": y, "cols": {}})
            slot["cols"][col] = t

    rows: list[list[int]] = []
    by_block: dict[int, list[tuple[float, list[int]]]] = collections.defaultdict(list)
    for (blk, _ri), slot in sorted(buckets.items()):
        cols = slot["cols"]
        if len(cols) != 3:
            # 只有「N 分及以下」标记、没有人数/累计 → 官方截断说明（2026 版式）
            if len(cols) == 1 and SCORE_OMIT_PAT.match(cols[0]):
                omits.append({"score_below":
                              int(SCORE_OMIT_PAT.match(cols[0]).group(1)), "omitted": True})
                continue
            dropped.append(f"组{blk} y={slot['y']:.1f} 只有 {len(cols)} 格: "
                           + " | ".join(cols[k] for k in sorted(cols)))
            continue
        score_t, seg_t, cum_t = cols[0], cols[1], cols[2]
        m = SCORE_PAT.match(score_t)
        mo = SCORE_OMIT_PAT.match(score_t)
        if not m and not mo:
            dropped.append(f"组{blk} y={slot['y']:.1f} 分数格异常: {score_t!r}")
            continue
        if not cum_t.isdigit():
            dropped.append(f"组{blk} y={slot['y']:.1f} 累计格异常: {cum_t!r}")
            continue
        cum = int(cum_t)
        if mo:
            # 「N 分及以下」：印了人数/累计就是末行桶（官方口径，接得上累计链）；
            # 只印标记（如 2026 的「200及以下 略」）才是截断说明。
            if seg_t.isdigit():
                belows.append({"score_below": int(mo.group(1)),
                               "seg": int(seg_t), "cum": cum})
            else:
                omits.append({"score_below": int(mo.group(1)), "omitted": True})
            continue
        seg = int(seg_t) if seg_t.isdigit() else cum  # 顶部截断桶人数留空时等于累计
        by_block[blk].append((slot["y"], [int(m.group(1)), seg, cum]))
    for blk in sorted(by_block):
        by_block[blk].sort(key=lambda r: -r[0])  # 组内自上而下
        rows.extend(r for _y, r in by_block[blk])  # 组间左右顺序
    return rows, omits, belows, dropped


def parse_pdf(pdf_bytes: bytes) -> tuple[dict[str, list[list[int]]],
                                         dict[str, dict], dict[str, dict]]:
    """返回 ({科类: rows}, {科类: 截断说明}, {科类: 末行桶})，按 PDF 页序拼接。"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        path = f.name
    out: dict[str, list[list[int]]] = collections.OrderedDict()
    notes: dict[str, dict] = {}
    belows: dict[str, dict] = {}
    dropped: list[str] = []
    try:
        for page in extract_pages(path):
            lines = _page_lines(page)
            subject = None
            for *_pos, t in lines:
                m = re.search(r"科类[:：]\s*([^\s（(]+)", t)
                if m:
                    subject = SUBJECT_OF_LABEL.get(m.group(1).strip())
                    break
            if not subject:
                continue  # 封面/说明页
            cells = _clean_lines(lines)
            head_y = max((y for _x0, _x1, y, t in lines if HEAD_PAT.search(t)), default=None)
            if head_y is None:
                continue
            data = [(x0, x1, y, t) for x0, x1, y, t in cells if y < head_y - 4]
            if not data:
                continue
            rows, omits, page_belows, drop = _parse_page(data)
            out.setdefault(subject, []).extend(rows)
            for o in omits:
                notes[subject] = o
            for b in page_belows:
                # 末行桶只可能出现在该科类的最后一页，后者覆盖前者
                belows[subject] = b
            dropped.extend(f"{subject} 第{page.pageid}页: {d}" for d in drop)
    finally:
        Path(path).unlink(missing_ok=True)
    if dropped:
        head = "；".join(dropped[:4])
        raise ValueError(f"安徽分档表有 {len(dropped)} 处文本未解析成完整行（拒收整份）：{head}")
    return out, notes, belows


def discover() -> dict[int, str]:
    """查省教育厅信息公开检索，返回 {year: 公告页}。

    每年的分档表都以「…考生成绩分档表（含加分）」为题、落在一个
    ``/public/7071/<id>.html`` 信息公开页上；新增年份无需改代码即可被发现。
    """
    from ..common import decode_html  # 局部导入，避免与 common 循环引用期的开销

    html = decode_html(http_get(SEARCH_URL, timeout=60))
    found: dict[int, str] = {}
    for url, _pid, title in ENTRY_PAT.findall(html):
        m = YEAR_PAT.search(title)
        if m:
            found.setdefault(int(m.group(1)), url)
    return found


def attachment_of(notice_url: str) -> str:
    """取信息公开页上的 PDF 附件地址（省教育厅原表）。"""
    from ..common import decode_html

    html = decode_html(http_get(notice_url, timeout=60))
    m = PDF_PAT.search(html)
    if not m:
        raise ValueError(f"安徽公告页未找到 PDF 附件: {notice_url}")
    return "https://jyt.ah.gov.cn" + m.group(1)


def source_url(year: int) -> str:
    if year in NOTICES:
        return NOTICES[year]
    if year in PDFS:
        # 2022–2024 无公告页（栏目 2025-06 才建），原表文件即来源
        return PDFS[year]
    found = discover()
    if year not in found:
        raise ValueError(f"安徽 {year} 分档表公告未找到（教育厅信息公开检索无结果）")
    return found[year]


def parse(year: int) -> dict:
    url = source_url(year)
    pdf = PDFS.get(year) or attachment_of(url)
    blob = http_get(pdf, timeout=180)
    by_subject, notes, belows = parse_pdf(blob)
    subjects: dict = {}
    for subj in SUBJECTS:
        rows = by_subject.get(subj) or []
        if not rows:
            raise ValueError(f"安徽 {year} {subj} 未解析出数据行")
        validate_rows(rows)
        # 顶部「X及以上」桶：人数与累计同值（2022–2026 各年版式一致）
        blk = {"rows": rows,
               "top_note": f"{rows[0][0]}↑" if rows[0][1] == rows[0][2] else ""}
        below = belows.get(subj)
        if below:
            if below["cum"] <= rows[-1][2]:
                raise ValueError(f"安徽 {year} {subj} 末行桶累计 {below['cum']} "
                                 f"不大于末行 {rows[-1][2]}，拒收")
            blk["below_bucket"] = below
        note = dict(notes.get(subj) or {})
        if note:
            # 「N 分以下略」：官方在原表末尾注明不再逐分列出，属口径事实，非漏行
            blk["omitted_below"] = note
        subjects[subj] = blk
    scheme = SCHEME if year >= 2024 else "文理分科"
    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": url,
        "attachment_url": pdf,
        "attachment_sha256": sha256(blob),
        "subject_scheme": scheme,
        "columns": 3,
        "tracks": {"primary": "含加分（含艺术、体育类考生，不含已录取考生、少年班）"},
        "note": ("一份 PDF 含两个科类，每页横向并排 3–5 组，按数据列右边界聚类后"
                 "组内自上而下、组间左右顺序重组；顶部「X及以上」人数与累计同值"),
        "fetched_at": now_iso(),
    }
    if scheme != SCHEME:
        # 2022/2023 官方表头写「文史/理工」，与 3+1+2 的科类等价映射
        meta["subject_aliases"] = {"历史类": "文史", "物理类": "理工"}
    return {"meta": meta, "subjects": subjects}
