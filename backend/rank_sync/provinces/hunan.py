"""湖南：hneeb.cn（湖南招生考试信息港）「普通高考档分 1 分段统计表」。

3+1+2，物理/历史分表，正文**服务端直出的 HTML 表格**（最省事的一种）：
``<tr><td>档分</td><td>本段人数</td><td>累计人数</td></tr>``。

三个口径细节：
- 「档分」**含优惠加分**，不是裸分；
- 表尾「100 分以下」桶在源 HTML 里首格也印成 ``100``（与上一行同分），
  解析器按「末行同分且累计能接上」识别并单列 ``below_bucket``，不混进 rows；
- 没有附件，溯源与内容固定都落在**页面本身**：``source_sha256`` 存 HTML 字节哈希。
"""
from __future__ import annotations

from ..common import (
    decode_html, http_get, now_iso, parse_html_table, sha256, validate_rows,
)

PROVINCE = "湖南"
SITE = "https://www.hneeb.cn"
SCHEME = "3+1+2"
SUBJECTS = ["物理类", "历史类"]
STATUS = "ready"

# content_4434=物理，content_4433=历史（2025）
NOTICES = {
    2025: {
        "物理类": "https://www.hneeb.cn/hnxxg/741/742/content_4434.html",
        "历史类": "https://www.hneeb.cn/hnxxg/741/742/content_4433.html",
    },
}


def parse(year: int) -> dict:
    pages = NOTICES[year]
    subjects: dict = {}
    shas: dict[str, str] = {}
    for subj, url in pages.items():
        blob = http_get(url)
        html = decode_html(blob)
        rows, top_note, below = parse_html_table(html)
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
            # 无附件：内容固定用页面字节哈希，和附件哈希同等的可核对性
            "source_sha256": shas.get("物理类", ""),
            "source_sha256_map": shas,
            "subject_scheme": SCHEME,
            "note": "档分含优惠加分；表尾「100 分以下」桶单列不进 rows；数据源为 HTML 表格",
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
