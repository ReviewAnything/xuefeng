#!/usr/bin/env python3
"""构建全国普通高等学校静态总表（本科 + 专科，约 2868 所）。

数据来源：教育部《全国普通高等学校名单》（截至 2024-06-20，共 2868 所：
本科 1308 + 高职专科 1560），官方 xls：
  http://www.moe.gov.cn/jyb_xxgk/s5743/s5744/A03/202406/W020240621412769813275.xls

用法：
  python scripts/build_universities_national.py                # 自动下载官方 xls
  python scripts/build_universities_national.py --xls FILE.xls # 使用本地 xls
  python scripts/build_universities_national.py --xls FILE.xls --no-website

派生属性：
  - province/city/level/nature/supervisor/code：来自官方名单
  - is_985 / is_211 / is_dfc / category / website：与权威 985/211 清单
    （backend/data/universities.json，112 所）及公开本科数据交叉填充

输出：backend/data/universities_national.json
"""
import argparse
import json
import os
import re
import sys
import urllib.request

MOE_XLS_URL = ("http://www.moe.gov.cn/jyb_xxgk/s5743/s5744/A03/202406/"
               "W020240621412769813275.xls")
CSV_URL = "https://raw.githubusercontent.com/luhuadong/open-edu-data/main/data/china-universities.csv"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# 官方省分组名 → 项目统一简称
PROVINCE_MAP = {
    "北京市": "北京", "天津市": "天津", "河北省": "河北", "山西省": "山西",
    "内蒙古自治区": "内蒙古", "辽宁省": "辽宁", "吉林省": "吉林", "黑龙江省": "黑龙江",
    "上海市": "上海", "江苏省": "江苏", "浙江省": "浙江", "安徽省": "安徽",
    "福建省": "福建", "江西省": "江西", "山东省": "山东", "河南省": "河南",
    "湖北省": "湖北", "湖南省": "湖南", "广东省": "广东", "广西壮族自治区": "广西",
    "海南省": "海南", "重庆市": "重庆", "四川省": "四川", "贵州省": "贵州",
    "云南省": "云南", "西藏自治区": "西藏", "陕西省": "陕西", "甘肃省": "甘肃",
    "青海省": "青海", "宁夏回族自治区": "宁夏", "新疆维吾尔自治区": "新疆",
}


def _norm_province(raw: str) -> str:
    raw = raw.strip()
    if raw in PROVINCE_MAP:
        return PROVINCE_MAP[raw]
    # 兜底：去掉后缀
    for suf in ("维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "省", "市"):
        if raw.endswith(suf):
            return raw[: -len(suf)]
    return raw


def _norm_nature(note: str) -> str:
    note = (note or "").strip()
    if "民办" in note:
        return "民办"
    if "中外合作" in note or "合作办学" in note:
        return "中外合作办学"
    if "境外" in note:
        return "境外办学"
    return "公办"


def _to_code(v) -> str:
    if v is None or v == "":
        return ""
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return str(v).strip()


def _download(url: str, dst: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r, open(dst, "wb") as f:
        f.write(r.read())
    return dst


def _load_authoritative():
    """读取权威 985/211 清单（112 所）与公开本科 CSV 作交叉填充。"""
    auth_path = os.path.join(DATA_DIR, "universities.json")
    by_name = {}
    if os.path.exists(auth_path):
        with open(auth_path, "r", encoding="utf-8") as f:
            for u in json.load(f).get("universities", []):
                by_name[u["name"]] = u
    csv_by_name = {}
    try:
        req = urllib.request.Request(CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
        text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8-sig")
        lines = text.splitlines()
        header = lines[0].split(",")
        idx = {h: i for i, h in enumerate(header)}
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < len(header):
                continue
            name = parts[idx["name"]].strip()
            csv_by_name[name] = {
                "project_985": parts[idx["project_985"]].strip() == "1",
                "project_211": parts[idx["project_211"]].strip() == "1",
                "website": parts[idx["website"]].strip(),
            }
    except Exception as e:  # 网络不可用时降级
        print(f"[warn] 读取公开 CSV 失败（将仅用权威清单）：{e}", file=sys.stderr)
    return by_name, csv_by_name


def build(xls_path=None, use_website=True):
    import xlrd  # 延迟导入，便于报错提示

    if not xls_path:
        tmp = os.path.join("/tmp", "gxmd_moe.xls")
        print(f"[info] 下载教育部官方名单：{MOE_XLS_URL}")
        xls_path = _download(MOE_XLS_URL, tmp)
    if not os.path.exists(xls_path):
        raise SystemExit(f"找不到 xls：{xls_path}")

    auth_by_name, csv_by_name = _load_authoritative()

    wb = xlrd.open_workbook(xls_path)
    sh = wb.sheet_by_index(0)

    records = []
    province = None
    for r in range(sh.nrows):
        vals = [sh.cell_value(r, c) for c in range(sh.ncols)]
        name = str(vals[1]).strip()
        # 省分组表头：col0 形如 "北京市（92所）"，col1 为空
        if not name and isinstance(vals[0], str) and "（" in vals[0]:
            province = _norm_province(re.sub(r"（.*?）", "", vals[0]))
            continue
        if not name or name == "学校名称":
            continue
        level = str(vals[5]).strip()
        if level not in ("本科", "专科"):
            continue
        note = str(vals[6]).strip()
        rec = {
            "name": name,
            "province": province,
            "city": str(vals[4]).strip(),
            "level": level,
            "nature": _norm_nature(note),
            "supervisor": str(vals[3]).strip(),
            "code": _to_code(vals[2]),
            "is_985": False,
            "is_211": False,
            "is_dfc": False,
            "category": None,
            "website": None,
        }
        # 权威 985/211 清单优先（含"中国石油大学（北京）"等拆分校区回退到本部）
        a = auth_by_name.get(name)
        if a is None:
            base = re.sub(r"[（(].*?[）)]\s*$", "", name).strip()
            a = auth_by_name.get(base)
        if a:
            rec["is_985"] = bool(a.get("is_985"))
            rec["is_211"] = bool(a.get("is_211"))
            rec["is_dfc"] = bool(a.get("is_dfc", rec["is_985"] or rec["is_211"]))
            rec["category"] = a.get("category")
            if use_website and a.get("website"):
                rec["website"] = a["website"]
        else:
            c = csv_by_name.get(name)
            if c is None:
                base = re.sub(r"[（(].*?[）)]\s*$", "", name).strip()
                c = csv_by_name.get(base)
            if c:
                rec["is_985"] = c["project_985"]
                rec["is_211"] = c["project_211"]
                rec["is_dfc"] = c["project_985"] or c["project_211"]
                if use_website and c.get("website"):
                    rec["website"] = c["website"]
        records.append(rec)

    count_985 = sum(1 for x in records if x["is_985"])
    count_211 = sum(1 for x in records if x["is_211"])
    count_benke = sum(1 for x in records if x["level"] == "本科")
    count_zhuanke = sum(1 for x in records if x["level"] == "专科")

    out = {
        "meta": {
            "source": "教育部《全国普通高等学校名单》(截至 2024-06-20)",
            "source_url": MOE_XLS_URL,
            "count": len(records),
            "count_benke": count_benke,
            "count_zhuanke": count_zhuanke,
            "count_985": count_985,
            "count_211": count_211,
            "note": ("教育部官方全国普通高等学校名单，含本科 1308 + 高职专科 1560。"
                     "is_985/is_211/is_dfc 由权威 985/211 清单(112 所)及公开本科数据交叉标注；"
                     "category(门类) 仅 985/211 院校有，专科及普通本科未细分；"
                     "nature 依官方备注区分 公办/民办/中外合作办学/境外办学。"),
        },
        "universities": records,
    }
    out_path = os.path.join(DATA_DIR, "universities_national.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[ok] 写出 {out_path}")
    print(f"[ok] 总计 {len(records)} 所（本科 {count_benke} / 专科 {count_zhuanke}），"
          f"985 {count_985}、211 {count_211}")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--xls", default=None, help="本地教育部名单 xls 路径（不传则自动下载）")
    ap.add_argument("--no-website", action="store_true", help="不填充官网")
    args = ap.parse_args()
    build(args.xls, use_website=not args.no_website)
