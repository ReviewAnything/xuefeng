"""内蒙古：nm.zsks.cn（内蒙古招生考试信息网）「各分数段人数统计表」。

形态在 31 省里最特殊：**每个科类一篇文章**，正文是一张**只有两列**的 HTML 表
（``分数 | 累计人数``）——官方根本不印「本段人数」，本段只能用相邻累计差反算。
所以本省落盘的 ``rows`` 里第 2 列是**派生值**（``meta.derived_seg = True`` 留痕），
第 3 列累计才是源表原值。反算公式与口径：

- ``seg(最高分) = cum(最高分)``（表是从最高分逐个往下印的，顶部不截断）；
- ``seg(s) = cum(s) − cum(上一个印出来的分数)``——官方**不印 0 人的分数段**，
  被跳过的分数累计与上一行相同，所以这个差正好是本段人数；
- 若某行 ``cum`` 不大于上一行（差为 0 或负数），说明列读错了，整份拒收。

两年一代口径：2023/2024 是 **文理分科**（``-文科``/``-理科``，落盘映射为历史类/物理类
并留痕 ``subject_aliases``），2025 起 3+1+2（``-历史类``/``-物理类``）。
**2023 那年的行标签全部写成 ``638及以上``**（2024 起才改回纯数字），两种都要吃。

发布位置是每年一个「高考统计信息」专题 ``/fzlm/{YY}gktj/``，里面几十篇文章：
普通类两份（历史类/物理类）、``（专项类）`` 变体、艺术各类、体育类、职高各类
（幼师/医学/汽驾/烹饪/农学/牧医/美工设计/旅游/建筑/计算机/机电/化工/采矿/财会）。
``pick_files`` 只认标题**以 ``统计表-历史类``/``-物理类``/``-文科``/``-理科`` 结尾**
的那一份——「国家专项计划-物理类」「艺术-音乐类」之类标题后缀都不长这样，自动排除。

两个站点级坑：
1. **证书链在 requests/OpenSSL 下握手失败**（本站直接 SSLError），全靠 ``http_get``
   的 curl 兜底；不是反爬。
2. 专题列表是 ``index.html / index_1.html …``（``index_1`` 是第 2 页，不是第 1 页），
   页数由内联脚本里的 ``countPage`` 决定，翻到空页即止。
3. 站内检索要走前端自己的接口 ``/webServices/search/375?content=关键词``（JSON），
   2022 那年的专题页正文已被清空（只剩空列表），只能靠检索记录确认它曾发布过。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from ..common import (
    decode_html, http_get, http_get_html, now_iso, sha256, validate_rows,
)

PROVINCE = "内蒙古"
SITE = "https://www.nm.zsks.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

_T = "https://www.nm.zsks.cn/fzlm/{}gktj/{}/{}.html"
SOURCES = {
    2023: {
        "topic": SITE + "/fzlm/23gktj/",
        "files": {"历史类": _T.format(23, "202306", "t20230623_43896"),
                  "物理类": _T.format(23, "202306", "t20230623_43897")},
    },
    2024: {
        "topic": SITE + "/fzlm/24gktj/",
        "files": {"历史类": _T.format(24, "202406", "t20240623_44816"),
                  "物理类": _T.format(24, "202406", "t20240623_44817")},
    },
    2025: {
        "topic": SITE + "/fzlm/25gktj/",
        "files": {"历史类": _T.format(25, "202506", "t20250624_45796"),
                  "物理类": _T.format(25, "202506", "t20250624_45794")},
    },
    2026: {
        "topic": SITE + "/fzlm/26gktj/",
        "files": {"历史类": _T.format(26, "202606", "t20260624_46464"),
                  "物理类": _T.format(26, "202606", "t20260624_46462")},
    },
}

KNOWN_GAPS = {
    2022: "2022 专题页 /fzlm/22gktj/ 的文章列表已清空（只剩空壳，无任何科类文章），"
          "同目录下按日期/ID 探测也不存在；检索接口只留一条指向该空页的记录——不臆造",
}

# 2023/2024 官方是文理分科
ALIASES = {2023: {"历史类": "文科", "物理类": "理科"},
           2024: {"历史类": "文科", "物理类": "理科"}}

HEADER = ("分数", "累计人数")
ROW_PAT = re.compile(r"^(\d{3})(?:及以上|以上)?$")
TITLE_WORDS = re.compile(r"统计表-(历史类|物理类|文科|理科)$")
# 专题列表里要挡掉的：专项类变体、艺术、体育、职高各类
AUX_PAT = re.compile(r"专项|艺术|体育|职高|幼师|医学|汽驾|烹饪|农学|牧医|美工|"
                     r"旅游|建筑|计算机|机电|化工|采矿|财会|对口")
TITLE_SEL = re.compile(r'<div class="gailan-xlTit">(.*?)</div>', re.S)


# ---------------------------------------------------------------------------
# 解析（纯函数）
# ---------------------------------------------------------------------------
def _cells(tr: str) -> list[str]:
    return [re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", c))
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]


def parse_table(html: str) -> dict:
    """两列表 -> {rows, cum, title, caption, note, top_note}。

    ``rows`` 是本段派生后的三列 ``[分数, 本段, 累计]``；``cum`` 是源表原值序列，
    单独留着便于核对反算。
    """
    title = ""
    m = TITLE_SEL.search(html)
    if m:
        title = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", m.group(1)))
    pairs: list[tuple[int, int]] = []
    caption = note = ""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = _cells(tr)
        if len(cells) == 2:
            mm = ROW_PAT.match(cells[0])
            if mm and cells[1].isdigit():
                score, cum = int(mm.group(1)), int(cells[1])
                if not (0 <= score <= 750):
                    raise ValueError(f"分数越界: {score}")
                pairs.append((score, cum))
                continue
            if cells[0] in HEADER:
                continue
        joined = "".join(cells)
        if joined.startswith("注：分数含") or joined.startswith("注:分数含"):
            caption = joined
        elif "仅统计本类考生" in joined:
            note = joined
    if not pairs:
        raise ValueError("内蒙古统计表未解析出任何数据行")

    rows: list[list[int]] = []
    prev = None
    for score, cum in pairs:
        seg = cum if prev is None else cum - prev
        if seg <= 0:
            raise ValueError(
                f"累计人数未递增（{score} 分：{prev} -> {cum}），列读错了，整份拒收")
        rows.append([score, seg, cum])
        prev = cum
    validate_rows(rows)
    return {
        "rows": rows,
        "cum": [c for _, c in pairs],
        "title": title,
        "caption": caption,
        "note": note,
        "top_note": f"{rows[0][0]}↑",
    }


def omitted_scores(rows: list[list[int]]) -> list[int]:
    """官方不印 0 人的分数段；累计链照样接得上。"""
    seen = {r[0] for r in rows}
    return [s for s in range(rows[0][0], rows[-1][0], -1) if s not in seen]


def subject_of_title(title: str) -> str:
    if "历史" in title or "文科" in title:
        return "历史类"
    if "物理" in title or "理科" in title:
        return "物理类"
    raise ValueError(f"内蒙古表名无法判定科类：{title!r}")


def title_ok(title: str, year: int, subj: str) -> bool:
    """表名守卫：``{年}年内蒙古普通高校招生考试各分数段人数统计表-{科类}``，
    后缀必须正好落在科类上（``-物理类（专项类）``、``-艺术-音乐类`` 都不匹配）。"""
    if AUX_PAT.search(title):
        return False
    if f"{year}年内蒙古普通高校招生考试各分数段人数统计表" not in title:
        return False
    m = TITLE_WORDS.search(title)
    return bool(m) and subject_of_title(m.group(1)) == subj


# ---------------------------------------------------------------------------
# 发现
# ---------------------------------------------------------------------------
def parse_anchors(html: str) -> list[tuple[str, str]]:
    """专题列表页 -> [(href, 标题)]（标题取 ``title=`` 属性，链接文字是截断的）。"""
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]*t\d{8}_\d+\.html)"[^>]*title="([^"]*)"',
                         html, re.S):
        out.append((m.group(1), re.sub(r"\s+", "", m.group(2))))
    return out


def pick_files(pairs: list[tuple[str, str]], year: int) -> dict[str, str]:
    """从几十条文章里挑出普通类两份（纯函数）。"""
    out: dict[str, str] = {}
    for href, title in pairs:
        if AUX_PAT.search(title):
            continue
        m = TITLE_WORDS.search(title)
        if not m or f"{year}年" not in title:
            continue
        out.setdefault(subject_of_title(m.group(1)), href)
    missing = [s for s in SUBJECTS if s not in out]
    if missing:
        raise ValueError(f"内蒙古 {year} 专题页缺普通类文章：{missing}")
    return out


def _topic(year: int) -> str:
    return (SOURCES.get(year) or {}).get("topic") or f"{SITE}/fzlm/{str(year)[2:]}gktj/"


def discover(year: int) -> dict:
    """翻该年专题列表页，返回 {topic, files}。新增年份时用它校正 SOURCES。"""
    topic = _topic(year)
    pairs: list[tuple[str, str]] = []
    for i in range(0, 8):
        url = topic + ("index.html" if i == 0 else f"index_{i}.html")
        try:
            html = http_get_html(url)
        except Exception:      # noqa: BLE001 - 翻到空页/404 即止
            break
        got = parse_anchors(html)
        if not got:
            break
        pairs.extend(got)
    picked = pick_files(pairs, year)
    return {"topic": topic, "files": {s: urljoin(topic, u) for s, u in picked.items()}}


def source(year: int) -> dict:
    return SOURCES.get(year) or discover(year)


# ---------------------------------------------------------------------------
# 取数
# ---------------------------------------------------------------------------
def parse(year: int) -> dict:
    src = source(year)
    subjects: dict = {}
    shas: dict[str, str] = {}
    urls: dict[str, str] = {}
    for subj in SUBJECTS:
        url = src["files"][subj]
        blob = http_get(url, timeout=180)
        got = parse_table(decode_html(blob))
        if not title_ok(got["title"], year, subj):
            raise ValueError(
                f"内蒙古 {year} 文章不是普通类分数段统计表（表名：{got['title']!r}），拒收")
        rows = got["rows"]
        subjects[subj] = {
            "rows": rows,
            "cum": got["cum"],
            "top_note": got["top_note"],
            "total": rows[-1][2],
            "score_floor": rows[-1][0],
            "omitted_scores": omitted_scores(rows),
            "table_title": got["title"],
        }
        shas[subj], urls[subj] = sha256(blob), url
    meta = {
        "year": year, "province": PROVINCE, "data_source": "official",
        "source_url": urls.get("物理类", ""),
        "source_url_map": urls,
        "topic_url": src.get("topic", ""),
        # 无附件：内容固定用页面字节哈希
        "source_sha256": shas.get("物理类", ""),
        "source_sha256_map": shas,
        "subject_scheme": "文理分科" if year <= 2024 else SCHEME,
        "columns": 3,
        "source_columns": 2,
        "derived_seg": True,
        "derived_seg_note": ("官方只印「分数|累计人数」两列，本段=相邻累计差"
                             "（0 人分段不印，累计不受影响）；累计列为源表原值，"
                             "另存 subjects.*.cum 供核对"),
        "tracks": {"primary": "分数含照顾分（官方表头注明）"},
        "caption": "注：分数含照顾分",
        "note": ("官方口径：仅统计本类考生（普通类首选科目为物理/历史的考生），"
                 "不含原民族语言授课考生与艺术类、体育类考生"),
        "per_subject_note": {s: b.get("table_title", "") for s, b in subjects.items()},
        "score_floor": {s: v["score_floor"] for s, v in subjects.items()},
        "fetched_at": now_iso(),
    }
    if year in ALIASES:
        meta["subject_aliases"] = ALIASES[year]
    if year in KNOWN_GAPS:
        meta["known_gap"] = KNOWN_GAPS[year]
    return {"meta": meta, "subjects": subjects}
