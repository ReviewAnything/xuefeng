"""近五年官方省控线（年度罗盘数据层）。

数据文件：backend/data/admission_control_lines_2022_2026.json
来源：阳光高考(gaokao.chsi.com.cn) 逐年官方录取控制分数线主表，覆盖 2022–2026 共 31 省。

设计：
  - 这是「按年浏览 / 罗盘」的权威只读数据源，不进入按位次的实时冲稳保排名
    （省控线主表不含一分一段位次，min_rank 留空，避免与位次混用误导）。
  - 实时排名仍由 admission_baselines 当前生效年份的估算/官方行驱动；本模块只按年查询。
"""
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_DATA_FILE = os.path.join(_DATA_DIR, "admission_control_lines_2022_2026.json")

_cache = None


def _load() -> dict:
    global _cache
    if _cache is None:
        if not os.path.exists(_DATA_FILE):
            _cache = {"meta": {}, "by_year": {}}
            return _cache
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def invalidate_cache() -> None:
    global _cache
    _cache = None


def meta() -> dict:
    return _load().get("meta", {})


def years() -> list[int]:
    return [int(y) for y in meta().get("years", [])]


def available_years() -> dict:
    """可用年份 + 覆盖省份数 + 每年来源链接。"""
    d = _load()
    m = d.get("meta", {})
    out = {}
    for y in m.get("years", []):
        blk = d.get("by_year", {}).get(str(y))
        provinces = sorted(blk["batch_lines"].keys()) if blk else []
        out[str(y)] = {
            "year": int(y),
            "province_count": len(provinces),
            "provinces": provinces,
            "source_url": m.get("sources", {}).get(str(y), ""),
        }
    return {
        "years": [int(y) for y in m.get("years", [])],
        "coverage_count": m.get("coverage_count", 0),
        "rank_included": m.get("rank_included", False),
        "source_name": m.get("source_name", ""),
        "note": m.get("note", ""),
        "rank_note": m.get("rank_note", ""),
        "normalized_note": m.get("normalized_note", ""),
        "by_year": out,
    }


def get_control_lines(year: int, province: str | None = None) -> dict:
    """取某年省控线。

    返回：
      { year, source_url, provinces_seen, data: { 省: { 科类: { 档位: {line,score} } } } }
    province 给定时只返回该省。
    """
    d = _load()
    m = d.get("meta", {})
    blk = d.get("by_year", {}).get(str(year))
    if not blk:
        return {
            "year": int(year),
            "source_url": m.get("sources", {}).get(str(year), ""),
            "ok": False,
            "error": f"暂无 {year} 年省控线（可用：{m.get('years')}）",
            "data": {},
        }
    batch = blk.get("batch_lines", {})
    if province:
        data = {province: batch.get(province, {})}
    else:
        data = batch
    return {
        "year": int(year),
        "source_url": m.get("sources", {}).get(str(year), ""),
        "ok": True,
        "rank_included": m.get("rank_included", False),
        "provinces_seen": len(batch),
        "data": data,
    }
