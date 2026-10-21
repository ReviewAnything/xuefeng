"""rank_segments 落库（服务层）。

口径与纪律：
- 按 (year, province, subject) 整组替换（delete-then-insert），幂等；
- 缺 ``source_url`` 的 JSON 整份拒收（**任何**来源的行都必须可溯源）；
- ``data_source`` 只接受 ``official`` 与 ``third_party_text``，并**原样落库**——
  第三方转录绝不能冒充 official，下游才能按来源区分可信度；
- 只写 ``rank_segments``，不改 ``admission_baselines`` / ``school_lines``。

``third_party_text`` 的由来：部分省官方一分一段表只以图片/扫描件发布（不 OCR），
改用「经核实的第三方文本转录」（gaokao.eol.cn 等）补齐，见 rank_sync/。
它是真实可核验的文本表，但**不是**省考试院原文，位次仅供参考。
"""
from __future__ import annotations

import json
from pathlib import Path

from db.database import session_scope
from db.models import RankSegment

DATA = Path(__file__).resolve().parents[1] / "data" / "rank_tables"

# 允许的来源标签：official=省考试院原文；third_party_text=经核实的第三方文本转录
ALLOWED_SOURCES = ("official", "third_party_text")


def import_doc(doc: dict, *, source: str = "") -> dict:
    meta = doc.get("meta") or {}
    year, prov = meta.get("year"), meta.get("province")
    if not year or not prov:
        raise ValueError(f"{source or '<doc>'}: meta 缺 year/province")
    data_source = meta.get("data_source") or ""
    if data_source not in ALLOWED_SOURCES:
        raise ValueError(
            f"{source or prov}: data_source 必须是 {' / '.join(ALLOWED_SOURCES)}"
            f"，实际 {data_source!r}"
        )
    if not meta.get("source_url"):
        raise ValueError(f"{source or prov}: 缺 source_url（行必须可溯源）")
    subjects = doc.get("subjects") or {}
    total = 0
    with session_scope() as s:
        s.query(RankSegment).filter(
            RankSegment.year == year, RankSegment.province == prov,
            RankSegment.subject.in_(list(subjects)),
        ).delete(synchronize_session=False)
        for subj, blk in subjects.items():
            # 第三方转录页是「一科一 URL」，科类级 URL 比 meta 级更精确
            row_url = blk.get("source_url") or meta["source_url"]
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
                    data_source=data_source, source_url=row_url,
                ))
                total += 1
    return {"year": year, "province": prov, "rows": total, "subjects": list(subjects),
            "data_source": data_source}


def import_file(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return import_doc(doc, source=Path(path).name)
