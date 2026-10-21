"""重庆：cqksy.cn「各类考生分数段表」（一分段表），2022–2026 五年。

版式：**一科类一张 HTML 表**（``wk.htm`` 历史类含加分 / ``lk.htm`` 物理类含加分），
三列 ``分数段 | 人数 | 累计人数``，官方单独挂一个索引页 ``fdb.htm`` 链接各科类表。

各年的落点不同（都踩过）：
- 2026：``/uploadFile/infopub/2026/ptgk/yfd/``（**ptgk** = 普通高考，新目录）；
- 2025：``/uploadFile/infopub/2025/pg/yfd/``（**pg**，旧目录）；
- 2022–2024：原年度页已下线，官方 2025-06-25 发布「往年重庆市各类考生一分数段表」
  专页（``/uploadFile/infopub/2025/pg/hist/link_block.html``）留有归档副本，
  逐年一个 ``www{year}/{year}yfd.htm`` 索引页。归档页相对链接需 urljoin。
- 目录不存在时门户返回 **HTTP 200 + 首页 HTML**（软 404），不能只看状态码；
  判据是索引页标题是否含「分数段表」。

口径（官方表自带，不要臆造）：
- 顶部首行 ``663及以上`` 只印人数、不印累计 —— 该桶人数即累计；
- **官方不印「本段人数为 0」的分数段**：2024 物理缺 197/196/184/181、2026 物理缺 188、
  2024 历史缺 182 等，累计链仍然自洽。因此不能按「逐分连续」校验，
  只能记录缺口（``meta.gaps``）——静默当成漏行会导致误判。
- 表底止于 180 分（专科批线同值）；2023 物理止于 182（官方当年表就到这里），
  逐年的实际表底记进 ``meta.score_floor``。
- 「含加分」= 档案分（总分 + 政策加分），即投档位次口径。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from ..common import decode_html, http_get, now_iso, sha256, validate_rows

PROVINCE = "重庆"
SITE = "https://www.cqksy.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

# 索引页 → 科类表文件名（各年一致）
SUBJECT_FILES = {"历史类": "wk.htm", "物理类": "lk.htm"}

# 当年页：2026 起用 ptgk，2025 及以前用 pg。新年度先试 ptgk 再试 pg。
INDEX_TPLS = (
    SITE + "/uploadFile/infopub/{year}/ptgk/yfd/fdb.htm",
    SITE + "/uploadFile/infopub/{year}/pg/yfd/fdb.htm",
)

# 已知年份的索引页（2022–2024 为官方「往年」专页下的归档副本）
PAGES = {
    2022: SITE + "/uploadFile/infopub/2025/pg/hist/www2022/2022yfd.htm",
    2023: SITE + "/uploadFile/infopub/2025/pg/hist/www2023/2023yfd.htm",
    2024: SITE + "/uploadFile/infopub/2025/pg/hist/www2024/2024yfd.htm",
    2025: INDEX_TPLS[1].format(year=2025),
    2026: INDEX_TPLS[0].format(year=2026),
}
# 门户对应的发布条目（2025 = content_6645「重庆市2025年全国普通高校招生各类考生分数段表」，
# 往年 = content_6648「往年重庆市各类考生一分数段表」）本身只是跳转壳，其 url 字段
# 与 PAGES 里的索引页一致——所以 source_url 直接记索引页，不额外汇总公告页。
LEGACY_HUB = SITE + "/uploadFile/infopub/2025/pg/hist/link_block.html"

TOP_PAT = re.compile(r"^(\d{1,3})(?:分)?(?:及以上|以上)$")
SCORE_PAT = re.compile(r"^(\d{1,3})(?:分)?$")
BELOW_PAT = re.compile(r"^(\d{1,3})分?以下$")
HEAD_WORDS = ("分数段", "人数", "累计")
# 2022 的表是 WPS 导出的整页 HTML，带一行标题「2022年物理类含加分一分段表[志愿填报]」
TITLE_PAT = re.compile(r"(一分段表|分数段表|志愿填报)")
ANCHOR_PAT = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{2,40})\s*</a>', re.I)


def _cells(row_html: str) -> list[str]:
    return [re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", c).replace("&nbsp;", ""))
            for c in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row_html, re.I)]


def parse_table(html: str) -> tuple[list[list[int]], str, dict | None, list[str]]:
    """单科类表 → (rows, top_note, below_bucket, 未解析文本)。

    ``未解析文本`` 非空即整份拒收：官方表结构简单，任何落不进来的行都说明版式变了。
    """
    rows: list[list[int]] = []
    below: dict | None = None
    dropped: list[str] = []
    top_note = ""
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html, re.I):
        cells = _cells(tr)
        if not cells or not cells[0]:
            continue
        head = cells[0]
        if any(w in head for w in HEAD_WORDS) or TITLE_PAT.search(head):
            continue  # 表头 / 标题行
        mt = TOP_PAT.match(head)
        if mt:
            nums = [c for c in cells[1:] if c]
            if not nums or not all(n.isdigit() for n in nums):
                dropped.append(" | ".join(cells))
                continue
            seg = int(nums[0])
            cum = int(nums[1]) if len(nums) > 1 else seg  # 只印人数 = 该桶即累计
            rows.append([int(mt.group(1)), seg, cum])
            top_note = f"{mt.group(1)}↑"
            continue
        mb = BELOW_PAT.match(head)
        if mb:
            nums = [c for c in cells[1:] if c]
            if len(nums) >= 2 and all(n.isdigit() for n in nums[:2]):
                below = {"score_below": int(mb.group(1)),
                         "seg": int(nums[0]), "cum": int(nums[1])}
            continue
        ms = SCORE_PAT.match(head)
        if ms:
            nums = [c for c in cells[1:] if c]
            if len(nums) == 2 and all(n.isdigit() for n in nums):
                rows.append([int(ms.group(1)), int(nums[0]), int(nums[1])])
                continue
            dropped.append(" | ".join(cells))
            continue
        dropped.append(" | ".join(cells))
    return rows, top_note, below, dropped


def _gaps(rows: list[list[int]]) -> list[int]:
    """官方未印出的分数段（本段人数为 0 的分数）。"""
    seen = {r[0] for r in rows}
    return [s for s in range(rows[-1][0], rows[0][0] + 1) if s not in seen]


def _subject_links(index_html: str, base: str) -> dict[str, str]:
    """从索引页取各科类表的绝对地址（相对链接需 urljoin）。"""
    out: dict[str, str] = {}
    for href, text in ANCHOR_PAT.findall(index_html):
        for subj in SUBJECTS:
            if subj in text and "一分段表" in text:
                out.setdefault(subj, urljoin(base, href))
    return out


def _is_index(html: str) -> bool:
    """软 404（门户首页）没有「分数段表」字样，据此识别。"""
    return "分数段表" in html


def discover(year: int) -> str:
    """按目录模板探测某年的索引页，返回其 URL。"""
    for tpl in INDEX_TPLS:
        url = tpl.format(year=year)
        try:
            html = decode_html(http_get(url, timeout=60))
        except Exception:
            continue
        if _is_index(html):
            return url
    raise ValueError(f"重庆 {year} 分数段表索引页未找到（ptgk/pg 两种目录均返回门户首页）")


def source_url(year: int) -> str:
    return PAGES.get(year) or discover(year)


def parse(year: int) -> dict:
    index_url = source_url(year)
    index_blob = http_get(index_url, timeout=60)
    index_html = decode_html(index_blob)
    if not _is_index(index_html):
        raise ValueError(f"重庆 {year} 索引页不是分数段表页（疑似门户首页/软 404）: {index_url}")
    links = _subject_links(index_html, index_url)
    if not links:
        # 索引页没挂链接时回退到约定文件名（同目录）
        links = {s: urljoin(index_url, f) for s, f in SUBJECT_FILES.items()}
    subjects: dict = {}
    for subj in SUBJECTS:
        url = links.get(subj)
        if not url:
            raise ValueError(f"重庆 {year} {subj} 索引页未找到对应表链接")
        blob = http_get(url, timeout=90)
        html = decode_html(blob)
        rows, top_note, below, dropped = parse_table(html)
        if dropped:
            raise ValueError(f"重庆 {year} {subj} 有 {len(dropped)} 行未解析（拒收整份）："
                             f"{'；'.join(dropped[:3])}")
        if len(rows) < 100:
            raise ValueError(f"重庆 {year} {subj} 只解析出 {len(rows)} 行，版式可能变了")
        validate_rows(rows)
        blk = {"rows": rows, "top_note": top_note}
        gaps = _gaps(rows)
        if gaps:
            # 官方不印「本段人数 0」的分数段，缺口是口径事实，不是漏行
            blk["omitted_scores"] = gaps
        if below:
            blk["below_bucket"] = below
        blk["_meta"] = {"url": url, "sha256": sha256(blob),
                        "floor": rows[-1][0], "top": rows[0][0],
                        "total": rows[-1][2]}
        subjects[subj] = blk
    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": index_url,
        "source_sha256": sha256(index_blob),
        "subject_scheme": SCHEME,
        "columns": 3,
        "tracks": {"primary": "含加分（档案分＝总分＋政策加分）"},
        "note": ("一科类一张 HTML 表，三列「分数段|人数|累计人数」；顶部「X及以上」"
                 "只印人数、累计同值；官方不印本段人数为 0 的分数段，缺口见 omitted_scores"),
        "fetched_at": now_iso(),
    }
    if year <= 2024:
        # 2022–2024 的原年度页已下线，来源是官方「往年」汇总页下的归档副本
        meta["archive_hub"] = LEGACY_HUB
    meta["source_sha256_map"] = {}
    meta["subject_url_map"] = {}
    meta["score_floor"] = {}
    for subj in SUBJECTS:
        info = subjects[subj].pop("_meta")
        meta["source_sha256_map"][subj] = info["sha256"]
        meta["subject_url_map"][subj] = info["url"]
        meta["score_floor"][subj] = info["floor"]
    return {"meta": meta, "subjects": subjects}
