"""各省高考志愿个数上限（S10-B）。

数据来源：阳光高考及各省教育考试院 2025 年招生规定汇总（见 volunteer_limits.json 的
meta.source_url）。每个省的「普通本科批 / 专科批」常规志愿数量是固定的（平行志愿模式下
可填满也可部分填），是志愿表草稿页做「上限提醒」的事实基准。

为什么单独成文件
----------------
录取数据层（admission.py）管的是「分数—位次—门槛」换算；志愿个数上限是另一类事实
（政策配额），与位次无关，混进 admission 基线反而模糊。单列后，端点只负责转发，
前端按省份查即可。

口径提醒
--------
- 上限是「本科批」总配额（含冲/稳/保全部）；提前批、艺术/体育类、征集志愿另算。
- 志愿模式分两类：``院校专业组``（广东/河南等，组内 6 专业 + 是否服从调剂）与
  ``专业+院校``（辽宁/河北等，每个志愿即一个「专业+学校」，无专业调剂选项）。
  ``旧高考``（新疆/西藏）为院校志愿模式，数量按常见设置填写，以本省考试院为准。
- 每年政策可能微调，故 JSON 标注 reference_year=2025，并强制要求前端展示「以本省考试院为准」。
"""
import json
import os

_DATA = os.path.join(os.path.dirname(__file__), "..", "data", "volunteer_limits.json")
_CACHE = {}


def _load() -> dict:
    if _CACHE.get("data") is None:
        with open(_DATA, "r", encoding="utf-8") as f:
            _CACHE["data"] = json.load(f)
    return _CACHE["data"]


def get(province: str) -> dict | None:
    """返回该省原始条目（mode/undergrad/junior/note），未知省份返回 None。"""
    if not province:
        return None
    return _load().get("provinces", {}).get(province)


def recommended_split(province: str) -> dict | None:
    """该省本科批志愿上限 + 建议的 冲/稳/保 志愿个数分布。

    分布优先取 JSON 里的 ``split_presets``（45/96/112 三档来自公开建议），
    其余按 冲 15% / 稳 50% / 保 35% 估算后取整（三档之和恰为上限）。
    返回 None 表示未知省份。
    """
    p = get(province)
    if not p:
        return None
    cap = int(p["undergrad"])
    presets = _load().get("split_presets", {})
    if str(cap) in presets:
        split = dict(presets[str(cap)])
    else:
        reach = round(cap * 0.15)
        safe = round(cap * 0.35)
        match = cap - reach - safe
        split = {"reach": reach, "match": match, "safe": safe}
    meta = _load().get("meta", {})
    return {
        "undergrad": cap,
        "junior": int(p["junior"]),
        "mode": p.get("mode", ""),
        "split": split,
        "note": p.get("note", ""),
        "reference_year": meta.get("reference_year"),
        "source": meta.get("source", ""),
        "source_url": meta.get("source_url", ""),
    }
