"""山东：sdzk.cn「夏季高考文化成绩一分一段表」。

3+3 综合改革，没有物理类/历史类：
- ``综合`` = 全体考生（唯一能当位次用的）；
- ``选考物理/化学/生物/思想政治/历史/地理`` = 该选考科目考生**内部**位次，
  与「物理类/历史类」不是一回事，meta 里用 ``subject_scheme=3+3`` 标注防混用。

附件是单个 .xls（BIFF，需 xlrd），表头两级：档位名 + 本段人数/累计人数。
"""
from __future__ import annotations

import hashlib

from ..common import (
    find_attachments, http_get, now_iso, parse_xls_tracks, validate_rows,
)

PROVINCE = "山东"
SITE = "https://www.sdzk.cn"
SCHEME = "3+3"
SUBJECTS = ["综合"]
STATUS = "ready"

NOTICES = {
    2026: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=7258",
    2025: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=6943",
    2024: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=6577",
    2023: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=6212",
    2022: "https://www.sdzk.cn/NewsInfo.aspx?NewsID=5794",
}


def parse(year: int) -> dict:
    notice_url = NOTICES[year]
    atts = find_attachments(notice_url)
    picked = [a for a in atts if "夏季高考" in a["label"] and "一分一段" in a["label"]]
    if not picked:
        raise ValueError(f"未找到夏季高考一分一段附件: {[a['label'] for a in atts]}")
    att = picked[0]
    blob = http_get(att["url"], timeout=180)
    tracks = parse_xls_tracks(blob)
    rejected = tracks.pop("_rejected", [])
    if "全体" not in tracks:
        raise ValueError(f"缺「全体」档位: {sorted(tracks)}")
    subjects: dict = {"综合": tracks.pop("全体")}
    for name, blk in tracks.items():
        validate_rows(blk["rows"])
        subjects[name] = blk
    for blk in subjects.values():
        blk["rows"].sort(key=lambda r: -r[0])
    return {
        "meta": {
            "year": year, "province": PROVINCE, "data_source": "official",
            "source_url": notice_url,
            "attachment_url": att["url"],
            "attachment_sha256": hashlib.sha256(blob).hexdigest(),
            "subject_scheme": SCHEME,
            "note": "综合=全体考生；选考X=该选考科目考生内部位次（非物理/历史类）",
            "rejected_tracks": rejected,
            "fetched_at": now_iso(),
        },
        "subjects": subjects,
    }
