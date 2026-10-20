"""一分一段表服务：读 data/rank_tables/ 落盘 JSON（官方转录，按年分目录）。

数据形态见 scripts/scrape_rank_tables.py 模块注释。位次口径：
``cum_ben``/``cum_zhuan`` 为该分数累计人数（= 该分数的最低位次），
本科档与专科档是两套不同位次，绝不能混用。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DATA = BACKEND / "data" / "rank_tables"


@lru_cache(maxsize=64)
def _load(path: str) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def years() -> list[dict]:
    """可用年份与覆盖概览：[{year, provinces: [{province, subjects: [...], rows}]}]"""
    out = []
    if not DATA.is_dir():
        return out
    for ydir in sorted(DATA.iterdir(), reverse=True):
        if not ydir.is_dir() or not ydir.name.isdigit():
            continue
        provs = []
        for f in sorted(ydir.glob("*.json")):
            doc = _load(str(f))
            if not doc:
                continue
            subs = doc.get("subjects") or {}
            provs.append({
                "province": doc["meta"]["province"],
                "subjects": sorted(subs.keys()),
                "rows": sum(len(v["rows"]) for v in subs.values()),
                "source_url": doc["meta"].get("source_url", ""),
            })
        if provs:
            out.append({"year": int(ydir.name), "provinces": provs})
    return out


def doc(year: int, province: str) -> dict | None:
    p = DATA / str(year) / f"{province}.json"
    return _load(str(p))


def lookup(year: int, province: str, subject: str, score: int) -> dict | None:
    """分数 -> 位次。分数不在表中时取「不高于该分的最近分数行」
    （其累计人数是此分数位次的上界，附 exact=False 标记）。
    """
    d = doc(year, province)
    if not d:
        return None
    blk = (d.get("subjects") or {}).get(subject)
    if not blk:
        return None
    rows = blk["rows"]  # score 降序
    chosen = None
    for r in rows:
        if r[0] <= score:
            chosen = r
            break
    if chosen is None:
        return None  # score 低于表内最低分（如 100 以下）
    return {
        "year": year, "province": province, "subject": subject,
        "score": score, "matched_score": chosen[0], "exact": chosen[0] == score,
        "cum_ben": chosen[2], "cum_zhuan": chosen[4],
        "source_url": d["meta"].get("source_url", ""),
    }
