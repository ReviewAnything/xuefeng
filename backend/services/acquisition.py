"""年度采集台账（P0）：31 省 × 年份 × 数据类的官方数据采集追踪。

为什么需要它：官方落库通道（S7-A/S8-A）只解决「怎么落」，不解决「缺哪补哪」。
各省考试院只在 6–8 月录取季公布原表，错过窗口就要再等一年——台账把
「哪省哪年哪类数据还没拿到」变成一眼可见的矩阵。

数据类（category）：
- ``control_lines`` 省控线（批次线）
- ``school_lines`` 逐校投档表
- ``rank_table`` 一分一段表

状态（status）：
- ``pending`` 待采集 / ``collected`` 原表到手 / ``ingested`` 已落库 / ``na`` 当年无公布

台账只记**采集进度**（JSON 落盘，``backend/data/acquisition_ledger.json``，已 gitignore），
数据本身仍走 official 落地区与各自导入通道。矩阵视图同时给出**库内实测覆盖**
（从 school_lines / rank_tables / 省控线文件推导），防止台账与实际两张皮：
状态说「已落库」但库里没有行的格子在页面上会被看穿。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlalchemy import func, select

from db.database import session_scope
from db.models import SchoolLine

CATEGORIES = {"control_lines": "省控线", "school_lines": "逐校投档", "rank_table": "一分一段表"}
STATUSES = {"pending": "待采集", "collected": "已采集", "ingested": "已落库", "na": "当年无公布"}

PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
]

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_BACKEND_DIR, "data")
LEDGER_PATH = os.path.join(DATA_DIR, "acquisition_ledger.json")

# 台账默认追踪的年份窗口：数据现状（省控线 2022–2026、一分一段 2022–2026）
# 决定下限；上限给到当前年份，供每年录取季滚动追加。
DEFAULT_YEAR_FROM = 2022


def _cell_key(year: int, province: str, category: str) -> str:
    return f"{int(year)}|{province}|{category}"


def load_ledger() -> dict:
    """读取台账（文件缺失/损坏按空台账处理，不抛错）。"""
    if not os.path.exists(LEDGER_PATH):
        return {"updated_at": None, "cells": []}
    try:
        with open(LEDGER_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        cells = [c for c in (doc.get("cells") or []) if isinstance(c, dict)]
        return {"updated_at": doc.get("updated_at"), "cells": cells}
    except (OSError, ValueError):
        return {"updated_at": None, "cells": []}


def upsert(year: int, province: str, category: str, status: str,
           source_url: str = "", source_org: str = "", note: str = "",
           operator: str = "system") -> dict:
    """登记/更新一格采集进度（按 年|省|数据类 幂等）。"""
    if category not in CATEGORIES:
        return {"ok": False, "error": f"未知数据类：{category}"}
    if status not in STATUSES:
        return {"ok": False, "error": f"未知状态：{status}"}
    if province not in PROVINCES:
        return {"ok": False, "error": f"省份无法识别：{province}"}
    if not 2000 <= int(year) <= 2100:
        return {"ok": False, "error": f"年份异常：{year}"}
    ledger = load_ledger()
    key = _cell_key(year, province, category)
    entry = {
        "year": int(year), "province": province, "category": category, "status": status,
        "source_url": str(source_url or ""), "source_org": str(source_org or ""),
        "note": str(note or ""), "operator": operator,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cells = [c for c in ledger["cells"] if _cell_key(c.get("year"), c.get("province", ""),
                                                     c.get("category", "")) != key]
    cells.append(entry)
    cells.sort(key=lambda c: (int(c.get("year") or 0), PROVINCES.index(c.get("province", "")) if c.get("province") in PROVINCES else 99, c.get("category", "")))
    doc = {"updated_at": entry["updated_at"], "cells": cells}
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LEDGER_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        return {"ok": False, "error": f"台账写入失败：{exc}"}
    return {"ok": True, "entry": entry, "count": len(cells)}


def _actual_coverage() -> dict:
    """库内/落盘数据的实测覆盖，键与台账一致：``年|省|数据类``。

    - school_lines：``school_lines`` 表 ``data_source=official`` 的行数；
    - rank_table：一分一段表落盘文件里该省该年的科类列表；
    - control_lines：省控线 JSON 里该省该年的批次数。
    """
    actual: dict[str, dict] = {}
    with session_scope() as s:
        rows = s.execute(
            select(SchoolLine.year, SchoolLine.province, func.count())
            .where(SchoolLine.data_source == "official")
            .group_by(SchoolLine.year, SchoolLine.province)).all()
    for year, prov, cnt in rows:
        actual[_cell_key(year, prov, "school_lines")] = {"rows": int(cnt)}

    from services import rank_tables as RT
    for ynode in RT.years():
        for pnode in ynode["provinces"]:
            actual[_cell_key(ynode["year"], pnode["province"], "rank_table")] = {
                "subjects": pnode["subjects"], "rows": pnode["rows"]}

    control_path = os.path.join(DATA_DIR, "admission_control_lines_2022_2026.json")
    try:
        with open(control_path, encoding="utf-8") as f:
            doc = json.load(f)
        # 层级：by_year[年]["batch_lines"][省][科类] → {批次: 线}
        for year, node in (doc.get("by_year") or {}).items():
            if not isinstance(node, dict):
                continue
            for prov, subjects in (node.get("batch_lines") or {}).items():
                if not isinstance(subjects, dict):
                    continue
                total = sum(len(v) for v in subjects.values() if isinstance(v, dict))
                if total:
                    actual[_cell_key(int(year), prov, "control_lines")] = {"rows": total}
    except (OSError, ValueError):
        pass
    return actual


def matrix() -> dict:
    """台账矩阵视图：登记状态 + 库内实测覆盖合并，供管理端按年渲染。"""
    ledger = load_ledger()
    actual = _actual_coverage()
    registered = {
        _cell_key(c.get("year"), c.get("province", ""), c.get("category", "")): c
        for c in ledger["cells"]
    }
    years = sorted({int(k.split("|")[0]) for k in list(registered) + list(actual)},
                   reverse=True)
    # 没有任何登记与实测时给默认窗口，页面不至于一片空白
    if not years:
        years = list(range(datetime.now().year, DEFAULT_YEAR_FROM - 1, -1))
    # 落库即证据：库里有 official 行 / 一分一段文件 / 省控线批次的格子，
    # 台账状态若仍停在 pending/collected，以实测为准提示「已落库」
    for key, info in actual.items():
        cell = registered.get(key)
        if cell is None:
            registered[key] = {
                "year": int(key.split("|")[0]), "province": key.split("|")[1],
                "category": key.split("|")[2], "status": "ingested",
                "source_url": "", "source_org": "", "note": "库内已有数据（自动标定）",
                "operator": "auto", "updated_at": None, "auto": True, **info,
            }
        else:
            cell["actual"] = info
    cells = {k: c for k, c in registered.items()}
    return {
        "years": years,
        "provinces": PROVINCES,
        "categories": CATEGORIES,
        "statuses": STATUSES,
        "cells": cells,
        "updated_at": ledger["updated_at"],
        "counts": {
            "registered": len(ledger["cells"]),
            "actual_cells": len(actual),
        },
    }
