"""陕西：sneea.cn（陕西省教育考试院）/ sneac.com（陕西招生考试信息网）。

**服务端直出的 HTML 表格**，三列 ``分数|人数|总人数``。看起来最简单，实际有
四个坑，全都会让「通用三列表解析」出错：

1. **顶部是截断桶且「人数」留空**：``710以上 | (空) | 11``。不能要求三格都有数，
   此时 ``人数 = 总人数``（即「710 分及以上共 11 人」）。
2. **分数不连续**：某分无人报考时该行整行不印（700 之后直接 698），
   所以不能拿「相邻分数差 1」当校验，只能校验严格递减 + 累计链。
3. **表尾是「N 分以下及缺考」**：含缺考人数，不是纯分数段，单列 below_bucket。
4. **2022–2024 是文理分科，2025 起才是 3+1+2**：表名分别是「理工/文史」与
   「物理/历史」。对外统一成 物理类/历史类（理科≈首选物理、文科≈首选历史），
   原始表头写进 ``meta.subject_aliases``，不静默改口径。

另一处口径：陕西表是「考生成绩统计表」（含政策性加分后的总分），
表头写「人数/总人数」，等价于本段/累计。
"""
from __future__ import annotations

import re

from ..common import decode_html, http_get, now_iso, sha256, validate_rows

PROVINCE = "陕西"
SITE = "https://www.sneea.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

_SNEEA = "https://www.sneea.cn/info/1027/{}.htm"
_SNEAC = "https://www.sneac.com/info/{}/{}.htm"

# 2022/2023/2024 为文理分科（理工=物理类、文史=历史类），2025 起为 3+1+2
NOTICES = {
    2022: {"物理类": _SNEAC.format(1024, 7681), "历史类": _SNEAC.format(1024, 7680)},
    2023: {"物理类": _SNEEA.format(12966), "历史类": _SNEEA.format(12965)},
    # 2024 文史只挂在 sneac（sneea 侧文章已下线）
    2024: {"物理类": _SNEEA.format(14886), "历史类": _SNEAC.format(1019, 17788)},
    2025: {"物理类": _SNEEA.format(16502), "历史类": _SNEEA.format(16503)},
    2026: {"物理类": _SNEEA.format(17658), "历史类": _SNEEA.format(17659)},
}
LABELS = {
    2022: {"物理类": "理工", "历史类": "文史"},
    2023: {"物理类": "理工", "历史类": "文史"},
    2024: {"物理类": "理工", "历史类": "文史"},
    2025: {"物理类": "物理", "历史类": "历史"},
    2026: {"物理类": "物理", "历史类": "历史"},
}

TOP_PAT = re.compile(r"^(\d{1,3})\s*分?\s*(?:及)?以上$")
BELOW_PAT = re.compile(r"^(\d{1,3})\s*分?\s*(?:及)?以下(?:[及或]?缺考)?$")
SCORE_PAT = re.compile(r"^(\d{1,3})(?:分)?$")


def parse_table(html: str) -> tuple[list[list[int]], str, dict | None]:
    """返回 ([[score, seg, cum], ...], top_note, below_bucket)。

    解析不出来的「看起来像数据行」必须报错而不是跳过——这里踩过：
    正则以 ``\\d{3}`` 开头时，50–99 分的低分档整段被静默丢弃，累计链依然自洽，
    校验器完全看不出来。宁可整份拒收，也不能少一段。
    """
    rows: list[list[int]] = []
    top_note = ""
    below: dict | None = None
    dropped: list[str] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [
            re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", c))
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        ]
        if len(cells) < 3:
            continue
        head, seg_t, cum_t = cells[0], cells[1], cells[2]
        if not cum_t.isdigit():
            continue
        cum = int(cum_t)
        m_top = TOP_PAT.match(head)
        if m_top:
            score = int(m_top.group(1))
            # 「人数」留空 = 该桶只有一个合计值，本段即累计
            seg = int(seg_t) if seg_t.isdigit() else cum
            rows.append([score, seg, cum])
            top_note = f"{score}↑"
            continue
        m_below = BELOW_PAT.match(head)
        if m_below:
            below = {"score_below": int(m_below.group(1)),
                     "seg": int(seg_t) if seg_t.isdigit() else 0, "cum": cum}
            continue
        m = SCORE_PAT.match(head)
        if m and seg_t.isdigit():
            rows.append([int(m.group(1)), int(seg_t), cum])
            continue
        if head[:1].isdigit():
            dropped.append(f"{head}|{seg_t}|{cum_t}")
    if dropped:
        raise ValueError(f"陕西表有 {len(dropped)} 行疑似数据未解析（拒绝半截落盘）: {dropped[:3]}")
    if not rows:
        raise ValueError("陕西表未解析出任何数据行")
    return rows, top_note, below


def parse(year: int) -> dict:
    pages = NOTICES[year]
    subjects: dict = {}
    shas: dict[str, str] = {}
    for subj, url in pages.items():
        blob = http_get(url)
        html = decode_html(blob)
        rows, top_note, below = parse_table(html)
        validate_rows(rows)
        blk = {"rows": rows, "top_note": top_note}
        if below:
            blk["below_bucket"] = below
        subjects[subj] = blk
        shas[subj] = sha256(blob)
    return {
        "meta": {
            "year": year, "province": PROVINCE, "data_source": "official",
            "source_url": pages.get("物理类", ""),
            "source_url_map": pages,
            "source_sha256": shas.get("物理类", ""),
            "source_sha256_map": shas,
            "subject_scheme": SCHEME,
            "subject_aliases": LABELS[year],
            "columns": 3,
            "tracks": {"primary": "考生成绩统计表（含政策性加分）"},
            "note": ("三列 分数/人数/总人数；顶部截断桶「X分及以上」人数留空即等于累计；"
                     "分数不连续（0 人的分整行不印）；表尾「N分以下及缺考」单列 below_bucket"),
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
