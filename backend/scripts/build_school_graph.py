#!/usr/bin/env python3
"""生成「学校图谱」静态数据（S9-C）→ shared/school_graph.json。

数据.compose 原则（与本项目一致的诚实口径）：
  - 院校底表来自教育部《全国普通高等学校名单》（2868 所，含 is_985/is_211/is_dfc 标注）；
  - 985 / 211 属国家工程名单（已统筹为「双一流」），直接取底表标注；
  - C9 / 华五 / 国防七子 / 两电一邮 / 五院四系 / 建筑老八校 / 两财一贸 属高校联盟或
    长期沿用的民间约定俗称，nature 一律标「民间约定」，绝不当成官方层次；
  - 部属师范六校是教育部直属师范大学，属官方口径；
  - 双一流：教育部第二轮（2022）共 147 所，底表只覆盖与 211 交叉的部分，因此标
    incomplete 并在 note 里写清缺口，避免被当成完整名单。

运行：python3 backend/scripts/build_school_graph.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(BASE, "backend", "data", "universities_national.json")
OUT = os.path.join(BASE, "shared", "school_graph.json")

MOE_URL = ("http://www.moe.gov.cn/jyb_xxgk/s5743/s5744/A03/202406/"
           "W020240621412769813275.xls")
DFC_URL = "https://www.moe.gov.cn/srcsite/a22/s7065/202202/w020220214318455516037.pdf"

# 联盟 / 俗称：nature 严格区分「高校联盟」「民间约定」「官方口径」
LEAGUES = [
    {
        "key": "c9", "name": "C9 联盟", "nature": "高校联盟",
        "desc": "2009 年 9 所高校签署《一流大学人才培养合作与交流协议书》，互换培养、互认学分。",
        "source_note": "联盟成立有公开协议可查；成员全部为 985。",
        "members": ["清华大学", "北京大学", "浙江大学", "复旦大学", "上海交通大学",
                    "南京大学", "中国科学技术大学", "哈尔滨工业大学", "西安交通大学"],
    },
    {
        "key": "huawu", "name": "华东五校", "nature": "民间约定",
        "desc": "华东地区五所顶尖高校的俗称，高考/保研话题里长期沿用。",
        "source_note": "无官方文件定义，属约定俗成；成员全部为 C9 成员。",
        "members": ["复旦大学", "上海交通大学", "浙江大学", "南京大学", "中国科学技术大学"],
    },
    {
        "key": "gf7", "name": "国防七子", "nature": "民间约定",
        "desc": "原国防科工委（现工信部等）直属、军工背景深厚的七所高校。",
        "source_note": "俗称，非官方名单；国防科大不在本表口径内。",
        "members": ["北京航空航天大学", "北京理工大学", "哈尔滨工业大学", "西北工业大学",
                    "南京航空航天大学", "南京理工大学", "哈尔滨工程大学"],
    },
    {
        "key": "dydy", "name": "两电一邮", "nature": "民间约定",
        "desc": "电子信息领域三所行业特色高校的合称。",
        "source_note": "俗称；就业口径常见，非官方层次。",
        "members": ["电子科技大学", "西安电子科技大学", "北京邮电大学"],
    },
    {
        "key": "wyxx", "name": "五院四系", "nature": "民间约定",
        "desc": "法学教育传统格局：五所政法院校 + 四所综合大学的法学学科。",
        "source_note": "俗称；部分成员非 211，层次不代表学科实力。",
        "members": ["中国政法大学", "西南政法大学", "华东政法大学", "中南财经政法大学",
                    "西北政法大学", "北京大学", "中国人民大学", "武汉大学", "吉林大学"],
    },
    {
        "key": "arch8", "name": "建筑老八校", "nature": "民间约定",
        "desc": "建筑学传统强校的合称，行业内认可度高。",
        "source_note": "俗称；西安建筑科技大学非 211，入选靠学科而非层次。",
        "members": ["清华大学", "同济大学", "东南大学", "天津大学", "哈尔滨工业大学",
                    "华南理工大学", "重庆大学", "西安建筑科技大学"],
    },
    {
        "key": "lcy", "name": "两财一贸", "nature": "民间约定",
        "desc": "财经类三所热门高校的合称。",
        "source_note": "俗称；三所均为 211。",
        "members": ["中央财经大学", "上海财经大学", "对外经济贸易大学"],
    },
    {
        "key": "sf6", "name": "部属师范六校", "nature": "官方口径",
        "desc": "教育部直属的六所师范大学，承担公费师范生、优师专项等培养任务。",
        "source_note": "教育部直属师范大学，六所均为 211。",
        "members": ["北京师范大学", "华东师范大学", "东北师范大学", "华中师范大学",
                    "陕西师范大学", "西南大学"],
    },
]

TIERS = [
    {
        "key": "985", "name": "985 工程", "nature": "官方工程",
        "desc": "1998 年起建设的世界一流大学工程（共 39 所），已统筹为「双一流」建设。",
        "note": "底表标注 38 所；国防科技大学为 985 但不在教育部普通高校名单内，故缺失。",
        "source_url": MOE_URL,
    },
    {
        "key": "211", "name": "211 工程", "nature": "官方工程",
        "desc": "面向 21 世纪重点建设 100 所左右高校的工程（共 112 所），已统筹为「双一流」建设。",
        "note": "底表标注 112 所，与公开 211 清单一致。",
        "source_url": MOE_URL,
    },
    {
        "key": "dfc", "name": "双一流（交叉标注）", "nature": "官方工程",
        "desc": "世界一流大学和一流学科建设高校；教育部第二轮（2022）公布 147 所。",
        "note": "⚠ 本图谱只覆盖与 211 清单交叉的 112 所，缺 35 所非 211 的双一流高校"
                "（如中国科学院大学、上海科技大学、南方科技大学、宁波大学等），"
                "因此此处标注不完整，不能当作「是否双一流」的判据，请以教育部名单为准。",
        "incomplete": True,
        "official_total": 147,
        "source_url": DFC_URL,
    },
]

CAVEAT = ("层次标签只说明学校的工程/联盟归属，不代表录取难度，也不代表专业强弱；"
          "「C9 / 华五 / 国防七子 / 两电一邮 / 五院四系 / 建筑老八校 / 两财一贸」"
          "均为高校联盟或民间约定俗称，不是官方层次。正式填报以各省考试院与院校招生章程为准。")


def load_universities() -> list[dict]:
    with open(DATA, "r", encoding="utf-8") as f:
        return json.load(f)["universities"]


def build() -> dict:
    rows = load_universities()
    by_name = {r["name"]: r for r in rows}

    tiers = []
    for t in TIERS:
        flag = {"985": "is_985", "211": "is_211", "dfc": "is_dfc"}[t["key"]]
        members = [r["name"] for r in rows if r.get(flag)]
        item = dict(t)
        item["count"] = len(members)
        item["members"] = members
        tiers.append(item)

    leagues = []
    unknown: dict[str, list[str]] = {}
    for lg in LEAGUES:
        members, missing = [], []
        for name in lg["members"]:
            if name in by_name:
                members.append(name)
            else:
                missing.append(name)
        if missing:
            unknown[lg["name"]] = missing
        composition = {"985": 0, "211": 0, "dfc": 0, "other": 0}
        for name in members:
            r = by_name[name]
            if r.get("is_985"):
                composition["985"] += 1
            if r.get("is_211"):
                composition["211"] += 1
            if r.get("is_dfc"):
                composition["dfc"] += 1
            if not (r.get("is_985") or r.get("is_211") or r.get("is_dfc")):
                composition["other"] += 1
        item = {k: v for k, v in lg.items() if k != "members"}
        item["count"] = len(members)
        item["members"] = members
        item["composition"] = composition
        item["composition_text"] = (
            f"{composition['985']} 所 985 · {composition['211'] - composition['985']} 所 211（非 985）"
            f" · {composition['other']} 所非 985/211"
        )
        leagues.append(item)

    # 学校清单：至少属于一个圈层/联盟的院校
    index: dict[str, dict] = {}
    for group in tiers + leagues:
        for name in group["members"]:
            r = by_name.get(name)
            if r is None:
                continue
            node = index.setdefault(name, {
                "name": name,
                "province": r.get("province", ""),
                "city": r.get("city", ""),
                "nature": r.get("nature", ""),
                "supervisor": r.get("supervisor", ""),
                "category": r.get("category", ""),
                "level": r.get("level", ""),
                "is_985": bool(r.get("is_985")),
                "is_211": bool(r.get("is_211")),
                "is_dfc": bool(r.get("is_dfc")),
                "groups": [],
            })
            if group["key"] not in node["groups"]:
                node["groups"].append(group["key"])

    schools = sorted(index.values(),
                     key=lambda s: (not s["is_985"], not s["is_211"], s["province"], s["name"]))

    provinces = sorted({s["province"] for s in schools if s["province"]})
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "教育部《全国普通高等学校名单》（截至 2024-06-20，2868 所）"
                      " + 985/211 权威清单 + 第二轮双一流名单（教育部官网）",
            "source_url": MOE_URL,
            "dfc_source_url": DFC_URL,
            "university_total": len(rows),
            "school_count": len(schools),
            "tier_counts": {t["key"]: t["count"] for t in tiers},
            "caveat": CAVEAT,
            "unmatched": unknown,
        },
        "tiers": tiers,
        "leagues": leagues,
        "provinces": provinces,
        "schools": schools,
    }


def main() -> int:
    data = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    m = data["meta"]
    print(f"已写入 {OUT}")
    print(f"  圈层：{m['tier_counts']}")
    print(f"  联盟：{[(l['name'], l['count']) for l in data['leagues']]}")
    print(f"  入图谱院校：{m['school_count']} 所 / 覆盖 {len(data['provinces'])} 省")
    if m["unmatched"]:
        print("  ⚠ 未匹配到教育部名单：", m["unmatched"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
