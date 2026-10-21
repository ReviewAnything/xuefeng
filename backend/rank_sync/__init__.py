"""按省一键同步：省级适配器的统一入口。

分层：
- ``provinces/<省>.py`` —— 该省的「发现 + 取数 + 解析」（唯一取数路径）；
- ``common.py`` —— 抓取/版式/强校验/落盘的公共底座；
- 本模块 —— 全国 31 省的看板与编排：谁 ready、谁 blocked、去年落到哪、这次同步
  成功还是失败，都在这里对账。

一致性纪律（与项目其它数据管线一致）：
- 官方行必须带可点开的 ``source_url``，缺则整份拒收；
- 校验不过（累计链断裂/列错位/非降序）整份拒收，绝不部分落盘；
- 失败不写「半份」文件：解析在内存完成，只有校验通过才落盘。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import common
from .provinces import REGISTRY

# 全国 31 个省级行政区（大陆），用于看板排序
ALL_PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
]

# 已探明硬阻碍：不要在每个批次重复踩，看板直接标 blocked 并写原因
BLOCKED = {
    "四川": "通知页正文是图片（26 张），无文本层也无附件——不 OCR 不臆造",
    "河北": "官方 4 份 PDF 均为扫描件（解析 0 行）——不 OCR",
    "江苏": "官方「逐分段统计表」通知页只挂 JPG 图片（44 张，无表格/附件）——不 OCR",
    "福建": "官方成绩分布以图片发布（转载页引用 wl-01.jpg 等 4 张/科类），未找到文本层或附件——不 OCR",
    "河南": "省考试院站返回 412 反爬（沙箱内不可取）",
    "山西": "站点在沙箱内不可达（连接超时）",
    "贵州": "站点在沙箱内不可达",
    "甘肃": "站点在沙箱内不可达",
    "天津": "站点在沙箱内不可达",
    "海南": "站点在沙箱内不可达",
}

STATUS_FILE = common.OUT_DIR / "_sync_status.json"


# ---------------------------------------------------------------------------
# 看板
# ---------------------------------------------------------------------------
def _covered(province: str) -> dict[int, dict]:
    """磁盘上已落盘年份 -> {subjects, rows}。"""
    out: dict[int, dict] = {}
    if not common.OUT_DIR.is_dir():
        return out
    for ydir in common.OUT_DIR.iterdir():
        if not ydir.is_dir() or not ydir.name.isdigit():
            continue
        p = ydir / f"{province}.json"
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        subs = doc.get("subjects") or {}
        out[int(ydir.name)] = {
            "subjects": sorted(subs),
            "rows": sum(len(v.get("rows") or []) for v in subs.values()),
        }
    return out


def _known_years(mod) -> set[int]:
    """适配器声明了哪些年份。登记位随省份形态不同：
    ``NOTICES``（公告页）、``PDFS``（原表文件）、``PAGES``（索引页）、
    ``SOURCES``（{年份: {notice, data}}）。取并集，新形态不必再改编排层。
    """
    out: set[int] = set()
    for attr in ("NOTICES", "PDFS", "PAGES", "SOURCES"):
        out |= set(getattr(mod, attr, {}) or {})
    return out


def entry(province: str) -> dict:
    """单省看板条目（注册表事实 + 磁盘事实 + 上次同步结果）。"""
    mod = REGISTRY.get(province)
    covered = _covered(province)
    last = (status().get("provinces") or {}).get(province)
    if mod is not None:
        years = sorted(_known_years(mod))
        return {
            "province": province,
            "status": "ready",
            "site": getattr(mod, "SITE", ""),
            "scheme": getattr(mod, "SCHEME", ""),
            "subjects": list(getattr(mod, "SUBJECTS", [])),
            "years": years,
            "known_gaps": getattr(mod, "KNOWN_GAPS", {}),
            "covered_years": sorted(covered),
            "covered": {str(y): v for y, v in sorted(covered.items())},
            "last_sync": last,
        }
    if province in BLOCKED:
        return {
            "province": province, "status": "blocked", "note": BLOCKED[province],
            "site": "", "scheme": "", "subjects": [], "years": [],
            "covered_years": sorted(covered),
            "covered": {str(y): v for y, v in sorted(covered.items())},
            "last_sync": last,
        }
    return {
        "province": province, "status": "planned", "note": "站点可达但尚未写适配器",
        "site": "", "scheme": "", "subjects": [], "years": [],
        "covered_years": sorted(covered),
        "covered": {str(y): v for y, v in sorted(covered.items())},
        "last_sync": last,
    }


def overview() -> dict:
    rows = [entry(p) for p in ALL_PROVINCES]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    covered_pairs = sum(len(r["covered_years"]) for r in rows)
    return {
        "provinces": rows,
        "counts": counts,
        "covered_province_years": covered_pairs,
        "total_provinces": len(ALL_PROVINCES),
    }


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------
def status() -> dict:
    if not STATUS_FILE.is_file():
        return {"provinces": {}}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"provinces": {}}


def _record(province: str, report: dict) -> None:
    doc = status()
    provs = doc.setdefault("provinces", {})
    prev = provs.get(province) or {}
    provs[province] = {
        "at": common.now_iso(),
        "ok": report["ok"],
        "saved": report["saved"],
        "failed": report["failed"],
        "years": [
            {k: r.get(k) for k in ("year", "ok", "rows", "subjects", "error", "skipped")}
            for r in report["years"]
        ],
        "previous_at": prev.get("at"),
    }
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def sync(province: str, years: list[int] | None = None, dry_run: bool = False,
         out_dir: Path | None = None) -> dict:
    """采一个省（可指定年份），逐年解析 → 强校验 → 落盘。

    返回逐年的明细，``ok`` 只有全部年份都成功才为 True。
    单年失败不影响其它年份（隔离失败），但失败原因会原样带回给调用方。
    """
    t0 = time.time()
    if province not in REGISTRY:
        hint = BLOCKED.get(province, "尚未实现该省适配器")
        return {"ok": False, "province": province, "error": hint,
                "years": [], "saved": 0, "failed": 0, "elapsed_ms": 0}
    mod = REGISTRY[province]
    known = _known_years(mod)
    wanted = sorted(years or known, reverse=True)
    results = []
    saved = failed = 0
    for year in wanted:
        if year not in known:
            gap = getattr(mod, "KNOWN_GAPS", {}).get(year)
            results.append({"year": year, "ok": False, "skipped": True,
                            "error": gap or "该年未登记通知页"})
            failed += 1
            continue
        try:
            doc = mod.parse(year)
            subs = doc.get("subjects") or {}
            rows = sum(len(v.get("rows") or []) for v in subs.values())
            if not dry_run:
                common.save(doc, out_dir)
            results.append({
                "year": year, "ok": True, "rows": rows,
                "subjects": {k: len(v.get("rows") or []) for k, v in subs.items()},
                "source_url": doc["meta"].get("source_url", ""),
                "attachment_sha256": doc["meta"].get("attachment_sha256", ""),
            })
            saved += 1
        except Exception as exc:  # noqa: BLE001 - 逐年隔离失败
            results.append({"year": year, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            failed += 1
    report = {
        "ok": failed == 0 and saved > 0,
        "province": province, "dry_run": dry_run,
        "years": results, "saved": saved, "failed": failed,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    if not dry_run:
        _record(province, report)
    return report
