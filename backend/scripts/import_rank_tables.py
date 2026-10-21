#!/usr/bin/env python3
"""把 data/rank_tables/ 的官方一分一段 JSON 落库到 rank_segments。

口径与纪律：
- 按 (year, province, subject) 整组替换（delete-then-insert），幂等；
- 缺 source_url 的 JSON 整份拒收（官方行必须可溯源）；
- 落库不改动 admission_baselines / school_lines，不影响实时排名。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import init_db, session_scope  # noqa: E402
from db.models import RankSegment  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "rank_tables"


def import_file(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    meta = doc.get("meta") or {}
    year, prov = meta.get("year"), meta.get("province")
    if not year or not prov:
        raise ValueError(f"{path.name}: meta 缺 year/province")
    if meta.get("data_source") != "official" or not meta.get("source_url"):
        raise ValueError(f"{path.name}: 官方行必须带 data_source=official 且有 source_url")
    subjects = doc.get("subjects") or {}
    total = 0
    with session_scope() as s:
        s.query(RankSegment).filter(
            RankSegment.year == year, RankSegment.province == prov,
            RankSegment.subject.in_(list(subjects)),
        ).delete(synchronize_session=False)
        for subj, blk in subjects.items():
            for row in blk["rows"]:
                # 5 列=双档位省（本科档/专科档分开）；3 列=单档位省（只公布一套累计，
                # 不存在本科/专科加分差异，故两档镜像同一数值，非伪造）
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="导入 data/rank_tables 全部年份")
    ap.add_argument("--year", type=int, default=0, help="只导入指定年份")
    args = ap.parse_args()

    init_db(seed=True)
    files = sorted(DATA.glob("*/*.json"))
    if args.year:
        files = [f for f in files if f.parent.name == str(args.year)]
    if not files:
        print("没有可导入的 rank_tables JSON")
        return 0
    ok = True
    for f in files:
        try:
            print("OK ", f.relative_to(DATA.parent), import_file(f))
        except Exception as e:  # noqa: BLE001
            ok = False
            print("FAIL", f.relative_to(DATA.parent), e)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
