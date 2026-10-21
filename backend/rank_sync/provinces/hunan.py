"""湖南：hneeb.cn（湖南招生考试信息港）「普通高考档分 1 分段统计表」。

3+1+2，物理/历史分表，正文**服务端直出的 HTML 表格**（最省事的一种）。
附件/图片都没有，因此溯源与内容固定都落在页面本身（``source_sha256``）。

列宽跨年变过口径，两种都要吃（解析器按列数自动判别）：
- **2022–2024：双轨 5 列** ``档分|本段|累计|本段|累计``，表头两行写明
  「(含全国性加分)」「(含全国性和地方性加分)」；
- **2025–2026：单轨 3 列** ``档分|本段|累计``，表头写「(含优惠加分)」。

双轨的主轨取**含全国性加分**（投档位次口径）；地方性加分那一轨单存
``alt_track``，不参与位次计算——它只对湖南省属高校生效，混用会低估位次。

三个口径细节：
- 「档分」**含优惠加分**，不是裸分；
- 表尾「100 分以下」桶：2024 起源表首格直接写 ``100以下``；2025 那张却
  也印成 ``100``（与上一行同分）。后者靠结构判据识别——末行同分且
  累计=前项+本段——单列 ``below_bucket``，不混进 rows；
- 页面是 **GBK**（``<meta charset="GBK">``），解码交给 ``decode_html``。

文章 ID 不是连续的（每年约 200 条），所以模块自带 ``discover()``：
翻「招考动态」列表页找标题，年份映射错了可以一键重扫。
"""
from __future__ import annotations

import re

from ..common import (
    decode_html, http_get, http_get_html, now_iso, parse_html_table, sha256,
    validate_rows,
)

PROVINCE = "湖南"
SITE = "https://www.hneeb.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

_ART = "https://www.hneeb.cn/hnxxg/741/742/content_{}.html"
# 物理在前、历史在后（源站历史类 ID 恒为物理类 -1，已逐年核对）
NOTICES = {
    2022: {"物理类": _ART.format(3610), "历史类": _ART.format(3609)},
    2023: {"物理类": _ART.format(3941), "历史类": _ART.format(3940)},
    2024: {"物理类": _ART.format(4207), "历史类": _ART.format(4206)},
    2025: {"物理类": _ART.format(4434), "历史类": _ART.format(4433)},
    2026: {"物理类": _ART.format(4687), "历史类": _ART.format(4686)},
}

# 列表页（招考动态，50 条/页，共 ~28 页）——discover() 用
LIST_BASE = "https://www.hneeb.cn/hnxxg/746/747/"
LIST_PAGES = 30
TITLE_PAT = re.compile(r"湖南省(\d{4})年普通高考档分1分段统计表[（(]([^）)]+)[）)]")
SUBJECT_OF = {"物理科目组合": "物理类", "历史科目组合": "历史类"}


def discover(year: int | None = None) -> dict[int, dict[str, str]]:
    """翻列表页，返回 {年份: {科类: 文章 URL}}。用于新增年份/校正 NOTICES。"""
    found: dict[int, dict[str, str]] = {}
    for pg in range(LIST_PAGES):
        url = LIST_BASE + ("index.htm" if pg == 0 else f"index_{pg}.htm")
        try:
            html = http_get_html(url)
        except Exception:
            continue  # 该页偶发 TLS 握手失败，跳过不影响其它页
        for href, title in re.findall(
            r'href="([^"]*content_(\d+)\.html)"[^>]*>(.*?)</a>', html, re.S
        ):
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()
            m = TITLE_PAT.search(text)
            if not m:
                continue
            yr, grp = int(m.group(1)), SUBJECT_OF.get(m.group(2))
            if not grp or (year and yr != year):
                continue
            found.setdefault(yr, {})[grp] = _ART.format(re.search(r"content_(\d+)", href).group(1))
    return found


def parse(year: int) -> dict:
    pages = NOTICES[year]
    subjects: dict = {}
    shas: dict[str, str] = {}
    widths: dict[str, int] = {}
    for subj, url in pages.items():
        blob = http_get(url)
        html = decode_html(blob)
        rows, top_note, below, alt = parse_html_table(html, tracks=True)
        validate_rows(rows)
        if alt:
            validate_rows(alt["rows"])  # 副轨也要能对上链，否则整份都不信
        blk = {"rows": rows, "top_note": top_note}
        if below:
            blk["below_bucket"] = below
        if alt:
            blk["alt_track"] = alt
        subjects[subj] = blk
        shas[subj] = sha256(blob)
        widths[subj] = 5 if alt else 3
    dual = any(w == 5 for w in widths.values())
    return {
        "meta": {
            "year": year, "province": PROVINCE, "data_source": "official",
            "source_url": pages.get("物理类", ""),
            "source_url_map": pages,
            # 无附件：内容固定用页面字节哈希，和附件哈希同等的可核对性
            "source_sha256": shas.get("物理类", ""),
            "source_sha256_map": shas,
            "subject_scheme": SCHEME,
            "columns": 5 if dual else 3,
            "tracks": ({"primary": "含全国性加分", "alt": "含全国性和地方性加分"}
                       if dual else {"primary": "含优惠加分"}),
            "note": ("档分含优惠加分；双轨表主轨取含全国性加分，地方性加分轨单列 alt_track；"
                     "表尾「100 分以下」桶单列不进 rows；数据源为 HTML 表格"),
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
