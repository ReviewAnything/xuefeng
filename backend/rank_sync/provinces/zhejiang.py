"""浙江：zjzs.net「普通高校招生成绩分数段表（总分）」。

3+3，全科类一张表（不区分物理/历史类），落地为 ``综合``。

两个必须记住的坑：
- 网上流传的「二段线上考生成绩分数段表」表内明示**不含录取考生**，顶部高分者
  已被录取剔除，拿它算位次会系统性偏低；必须认准「成绩分数段表（总分）」。
- 版式是**整页横向并排 3 组**「总分|人数|累计人数」，同一个 y 上的三格属于三个
  不同分数段——不能按 y 拼行，要按表头 x 切组（见 common._page_block_rows）。

栏目页是 JS 渲染、检索侧拿不到历史文章 ID，故 2022–2024/2026 需逐年人工定位。
"""
from __future__ import annotations

from urllib.parse import unquote, urljoin

from ..common import (
    find_attachments, http_get, now_iso, parse_blocked_pdf, sha256, validate_rows,
)

PROVINCE = "浙江"
SITE = "https://www.zjzs.net"
SCHEME = "3+3"
SUBJECTS = ["综合"]
STATUS = "ready"

NOTICES = {
    2025: "https://www.zjzs.net/art/2025/6/25/art_45_11373.html",
}
# 栏目页 JS 渲染 + 检索拿不到 ID，逐年待补（不是解析问题）
KNOWN_GAPS = {y: "文章 ID 需人工定位（栏目页 JS 渲染）" for y in (2022, 2023, 2024, 2026)}


def parse(year: int) -> dict:
    notice_url = NOTICES[year]
    atts = find_attachments(notice_url, kinds="pdf")
    picked = [
        a for a in atts
        if "分数段表" in unquote(a["url"]) and "总分" in unquote(a["url"])
    ] or [a for a in atts if "分数段" in a["label"]]
    if not picked:
        raise ValueError(f"未找到「成绩分数段表（总分）」附件: {[a['label'] for a in atts]}")
    att = picked[0]
    url = urljoin(notice_url, att["url"])
    blob = http_get(url, timeout=180)
    rows, top_note = parse_blocked_pdf(blob)
    validate_rows(rows)
    return {
        "meta": {
            "year": year, "province": PROVINCE, "data_source": "official",
            "source_url": notice_url, "attachment_url": url,
            "attachment_sha256": sha256(blob),
            "subject_scheme": SCHEME,
            "note": "综合=全体考生（浙江不区分物理/历史类）；表内分数区间为该年二段线及以上",
            "fetched_at": now_iso(),
        },
        "subjects": {"综合": {"rows": rows, "top_note": top_note}},
    }
