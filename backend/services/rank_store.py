"""rank_segments 落库（服务层）。

口径与纪律：
- 按 (year, province, subject) 整组替换（delete-then-insert），幂等；
- 缺 ``source_url`` 的 JSON 整份拒收（官方行必须可溯源）；
- 只写 ``rank_segments``，不改 ``admission_baselines`` / ``school_lines``。
"""
from __future__ import annotations

import json
from pathlib import Path

from db.database import session_scope
from db.models import RankSegment

DATA = Path(__file__).resolve().parents[1] / "data" / "rank_tables"


def import_doc(doc: dict, *, source: str = "") -> dict:
    meta = doc.get("meta") or {}
    year, prov = meta.get("year"), meta.get("province")
    if not year or not prov:
        raise ValueError(f"{source or '<doc>'}: meta 缺 year/province")
    if meta.get("data_source") != "official" or not meta.get("source_url"):
        raise ValueError(f"{source or prov}: 官方行必须带 data_source=official 且有 source_url")
    subjects = doc.get("subjects") or {}
    total = 0
    with session_scope() as s:
        s.query(RankSegment).filter(
            RankSegment.year == year, RankSegment.province == prov,
            RankSegment.subject.in_(list(subjects)),
        ).delete(synchronize_session=False)
        for subj, blk in subjects.items():
            for row in blk["rows"]:
                # 5 列=双档位（本科/专科加分位次不同）；3 列=单档位（只公布一套累计，
                # 两档镜像同一数值——语义是「该省没有双档」，不是伪造）
                if len(row) == 5:
                    score, sb, cb, sz, cz = row
                elif len(row) == 3:
                    score, sb, cb = row
                    sz, cz = sb, cb
                else:
                    raise ValueError(f"不支持的行宽 {len(row)}: {row}")
                s.add(RankSegment(
                    year=year, province=prov, subject=subj, score=score,
                    seg_ben=sb, cum_ben=cb, seg_zhuan=sz, cum_zhuan=cz,
                    data_source="official", source_url=meta["source_url"],
                ))
                total += 1
    return {"year": year, "province": prov, "rows": total, "subjects": list(subjects)}


def import_file(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return import_doc(doc, source=Path(path).name)
