"""院校投档线导入（D1）。

背景
----
`admission_official_*.json` 只到「省×科类×批次」的省控线，院校级投档线一直缺失
（`school_level_lines` 为空）。本模块把各省考试院/汇总表导出的 CSV/Excel 变成
`school_lines` 表：院校名先做规范化，再与教育部 2868 所名单匹配，最后落库。

设计原则
--------
- **不猜数据**：匹配不上的行不写库，进 `unmatched` 清单让人工确认；
- **可回溯**：保留原始校名（`university_input`）与匹配方式（`match_method`）；
- **幂等**：同一 (年份, 省, 科类, 院校, 专业组) 重复导入只更新，不重复插入；
- **先 dry-run**：默认只出报告，确认后才 `commit`。
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import os
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import func, select

from db.database import session_scope
from db.models import DataChange, SchoolLine

MAX_SCORE = 750
MAX_RANK = 2_000_000

PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
]

# 表头别名：越多越省事，匹配时统一小写去空格
HEADER_ALIASES = {
    "university": ["院校", "院校名称", "学校", "学校名称", "高校", "招生院校", "大学", "院校名"],
    "min_score": ["最低分", "投档分", "最低投档分", "院校最低分", "最低录取分", "投档线", "最低分数线", "分数",
                  # S8-A：省考试院原表常见写法（投档情况表多为「投档最低分 / 投档最低排位」）
                  "投档最低分", "最低投档成绩", "出档分", "提档分", "院校投档分", "投档最低成绩"],
    "min_rank": ["最低位次", "位次", "最低排名", "排名", "最低位次(名次)", "最低分位次", "位次号",
                  "投档最低排位", "最低排位", "投档位次", "投档最低位次", "最低投档位次", "排位",
                  "投档最低分排位", "末位投档考生排位"],
    "group_code": ["专业组", "院校专业组", "专业组代码", "专业组号", "组别", "科类代码",
                   "院校专业组代码", "院校专业组名称", "专业组名称", "专业代号", "志愿号"],
    "subject": ["科类", "选科", "文理", "科类名称", "选考科目"],
    "province": ["省份", "生源地", "招生省份", "省"],
    "year": ["年份", "年度", "招生年份"],
    "batch": ["批次", "录取批次", "批次名称"],
    "source_url": ["来源", "链接", "网址", "source_url", "数据来源"],
    "note": ["备注", "说明"],
}

_SUBJECT_MAP = {
    "物理": "物理类", "物理类": "物理类", "理科": "物理类", "理工": "物理类",
    "历史": "历史类", "历史类": "历史类", "文科": "历史类", "文史": "历史类",
    "综合": "综合", "不分文理": "综合", "综合改革": "综合",
}

# 校名里的「办学性质/收费类型」后缀，匹配前先剥掉
_SUFFIX_RE = re.compile(
    r"[（(][^（()）]*(中外合作|较高收费|高收费|软件类|医护类|农林类|单列|预科|民族班|"
    r"定向|专项|地方专项|国家专项|高校专项|中外|合作办学|国际课程|医学院|校区)[^（()）]*[）)]"
)
_BRACKET_RE = re.compile(r"[（(][^（()）]*[）)]")

_MATCH_CACHE: dict[str, tuple[list[str], dict[str, str]]] = {}
_LINES_CACHE: dict[tuple, float] = {}


# ---------------------------------------------------------------- 名称规范化

def norm_text(text: str) -> str:
    """全角转半角 + 去所有空白（校名里常混全角括号和空格）。"""
    s = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", "", s)


def clean_university(name: str) -> str:
    """剥离办学性质括号后缀，保留主体校名。"""
    s = norm_text(name)
    for _ in range(3):  # 支持「XX大学(中外合作)(较高收费)」多层
        new = _SUFFIX_RE.sub("", s)
        if new == s:
            break
        s = new
    return s


def _strip_brackets(name: str) -> str:
    return _BRACKET_RE.sub("", name)


def _uni_index() -> tuple[list[str], dict[str, str]]:
    """教育部名单 + 别名表（缓存到进程内）。

    直接读 JSON 全量（2868 所）：``admission.universities`` 的分页上限是 1000，
    用它建索引会漏掉大部分院校，导致校名匹配大面积失败。
    """
    cached = _MATCH_CACHE.get("index")
    if cached:
        return cached
    from services import admission as A

    items = (A._load_national() or {}).get("universities") or []
    names = [u["name"] for u in items if u.get("name")]
    alias: dict[str, str] = {}
    for n in names:
        alias[norm_text(n)] = n
        clean = clean_university(n)
        alias.setdefault(clean, n)
        alias.setdefault(_strip_brackets(clean), n)
    _MATCH_CACHE["index"] = (names, alias)
    return names, alias


def match_university(name: str) -> tuple[str | None, str, float]:
    """校名匹配：精确 → 规范化 → 去括号 → 包含 → 模糊。

    返回 (规范校名 | None, 匹配方式, 相似度)。
    """
    raw = norm_text(name)
    if not raw:
        return None, "empty", 0.0
    names, alias = _uni_index()
    if raw in alias:
        return alias[raw], "exact", 1.0

    clean = clean_university(raw)
    if clean in alias:
        return alias[clean], "normalized", 0.99

    bare = _strip_brackets(clean)
    if bare in alias:
        return alias[bare], "normalized", 0.98

    # 包含关系：输入是官方名的子串（或反之），且长度差不超过 6 字，避免「北京大学」命中「北京大学医学部」
    candidates = [n for n in names if (bare and (bare in n or n in bare)) and abs(len(n) - len(bare)) <= 6]
    if len(candidates) == 1:
        return candidates[0], "contains", 0.95
    if len(candidates) > 1:
        best = min(candidates, key=lambda n: abs(len(n) - len(bare)))
        return best, "contains", 0.9

    close = difflib.get_close_matches(bare or clean, names, n=1, cutoff=0.86)
    if close:
        score = difflib.SequenceMatcher(None, bare or clean, close[0]).ratio()
        return close[0], "fuzzy", round(score, 3)
    return None, "none", 0.0


# ---------------------------------------------------------------- 解析

def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _rows_from_csv(raw: bytes) -> list[list[str]]:
    text = _decode(raw)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        reader = csv.reader(io.StringIO(text), dialect)
    except csv.Error:
        reader = csv.reader(io.StringIO(text))
    return [list(r) for r in reader]


def _rows_from_xlsx(raw: bytes) -> list[list]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - 依赖缺失时才触发
        raise RuntimeError("解析 .xlsx 需要 openpyxl（pip install openpyxl）") from exc
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _canon_header(cell) -> str:
    return norm_text(str(cell or "")).lower().replace("_", "")


def _header_map(row: list) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(row):
        key = _canon_header(cell)
        if not key:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if field in mapping:
                continue
            if any(key == _canon_header(a) or key.endswith(_canon_header(a)) for a in aliases):
                mapping[field] = idx
                break
    return mapping


def _to_int(value) -> int | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("，", "")
    if s in {"", "-", "—", "–", "/", "无", "nan", "None"}:
        return None
    m = re.search(r"-?\d+", s)
    if not m:
        return None
    try:
        return int(m.group())
    except ValueError:
        return None


def _norm_subject(value: str) -> str:
    s = norm_text(value)
    return _SUBJECT_MAP.get(s, s)


def _norm_province(value: str) -> str:
    s = norm_text(value)
    return s[:-1] if s.endswith("省") and s[:-1] in PROVINCES else s


def parse_table(raw: bytes, filename: str = "") -> dict:
    """把上传文件解析成（表头映射 + 原始行）。只做结构识别，不校验业务值。"""
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm")):
        rows = _rows_from_xlsx(raw)
    elif lower.endswith(".xls"):
        raise RuntimeError("不支持旧版 .xls，请另存为 .xlsx 或 .csv")
    else:
        rows = _rows_from_csv(raw)

    if not rows:
        return {"ok": False, "error": "文件为空"}

    header_idx, mapping = -1, {}
    for i, row in enumerate(rows[:6]):  # 允许前几行是标题/说明
        m = _header_map(row)
        if "university" in m and ("min_score" in m or "min_rank" in m):
            header_idx, mapping = i, m
            break
    if header_idx < 0:
        return {"ok": False,
                "error": "未识别到表头：至少需要「院校名称」+「最低分」或「最低位次」列",
                "detected_headers": [str(c) for c in rows[0][:12]]}

    data = [r for r in rows[header_idx + 1:] if any(str(c or "").strip() for c in r)]
    return {"ok": True, "mapping": mapping, "header": [str(c or "") for c in rows[header_idx]],
            "rows": data, "header_index": header_idx}


def normalize_row(row: list, mapping: dict, defaults: dict) -> dict:
    """单行 → 结构化记录（含校验错误）。"""
    def cell(field: str):
        idx = mapping.get(field)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    errors: list[str] = []
    name_input = str(cell("university") or "").strip()
    if not name_input:
        return {"ok": False, "errors": ["院校名称为空"]}

    year = _to_int(cell("year")) or defaults.get("year") or 0
    if not (2000 <= year <= 2100):
        errors.append(f"年份异常：{year}")

    province = _norm_province(str(cell("province") or defaults.get("province") or ""))
    if province not in PROVINCES:
        errors.append(f"省份无法识别：{province or '空'}")

    subject = _norm_subject(str(cell("subject") or defaults.get("subject") or ""))
    if subject not in ("物理类", "历史类", "综合"):
        errors.append(f"科类无法识别：{subject or '空'}")

    score = _to_int(cell("min_score"))
    rank = _to_int(cell("min_rank"))
    if score is None and rank is None:
        errors.append("最低分与最低位次至少填一个")
    if score is not None and not (0 < score <= MAX_SCORE):
        errors.append(f"分数超出范围：{score}")
    if rank is not None and not (0 < rank <= MAX_RANK):
        errors.append(f"位次超出范围：{rank}")

    group = norm_text(str(cell("group_code") or ""))
    canonical, method, sim = match_university(name_input)

    return {
        "ok": not errors,
        "errors": errors,
        "year": year,
        "province": province,
        "subject": subject,
        "batch": norm_text(str(cell("batch") or "")),
        "university": canonical or "",
        "university_input": name_input[:128],
        "match_method": method,
        "match_score": sim,
        "group_code": group[:32],
        "min_score": score or 0,
        "min_rank": rank or 0,
        "source_url": str(cell("source_url") or "").strip()[:512],
        "note": str(cell("note") or "").strip()[:500],
    }


# ---------------------------------------------------------------- 导入

def import_table(raw: bytes, filename: str, defaults: dict, dry_run: bool = True,
                 operator: str = "system", mode: str = "merge") -> dict:
    """解析 + 校验 + 匹配 + （可选）落库，返回完整报告。"""
    parsed = parse_table(raw, filename)
    if not parsed.get("ok"):
        return parsed

    mapping = parsed["mapping"]
    unknown_headers = [h for h in parsed["header"] if h and not any(
        _canon_header(h) == _canon_header(a) or _canon_header(h).endswith(_canon_header(a))
        for aliases in HEADER_ALIASES.values() for a in aliases)]

    records, invalid, unmatched, seen = [], [], [], {}
    for offset, row in enumerate(parsed["rows"], start=1):
        rec = normalize_row(row, mapping, defaults)
        if not rec["ok"]:
            invalid.append({"row": offset + parsed["header_index"] + 1,
                            "university": rec.get("university_input", ""),
                            "errors": rec["errors"]})
            continue
        if not rec["university"]:
            unmatched.append({"row": offset + parsed["header_index"] + 1,
                              "university": rec["university_input"]})
            continue
        key = (rec["year"], rec["province"], rec["subject"], rec["university"], rec["group_code"])
        if key in seen:
            invalid.append({"row": offset + parsed["header_index"] + 1,
                            "university": rec["university_input"],
                            "errors": [f"文件内重复：与第 {seen[key]} 行同院校同专业组"]})
            continue
        seen[key] = offset + parsed["header_index"] + 1
        records.append(rec)

    report = {
        "ok": True,
        "dry_run": dry_run,
        "filename": filename,
        "total_rows": len(parsed["rows"]),
        "valid": len(records),
        "invalid_count": len(invalid),
        "unmatched_count": len(unmatched),
        "invalid": invalid[:50],
        "unmatched": unmatched[:200],
        "unknown_headers": unknown_headers,
        "matched_methods": {},
        "inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0,
        "scope": sorted({(r["year"], r["province"], r["subject"]) for r in records}),
        "preview": records[:10],
    }
    for r in records:
        report["matched_methods"][r["match_method"]] = report["matched_methods"].get(r["match_method"], 0) + 1
    report["match_rate"] = round(len(records) / max(1, len(records) + len(unmatched)), 4)

    if dry_run or not records:
        return report

    source_url = defaults.get("source_url") or next((r["source_url"] for r in records if r["source_url"]), "")
    data_source = defaults.get("data_source") or ("official" if source_url else "imported")
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        for rec in records:
            row = s.scalar(select(SchoolLine).where(
                SchoolLine.year == rec["year"], SchoolLine.province == rec["province"],
                SchoolLine.subject == rec["subject"], SchoolLine.university == rec["university"],
                SchoolLine.group_code == rec["group_code"]))
            if row is None:
                s.add(SchoolLine(
                    year=rec["year"], province=rec["province"], subject=rec["subject"],
                    batch=rec["batch"], university=rec["university"],
                    university_input=rec["university_input"], group_code=rec["group_code"],
                    min_score=rec["min_score"], min_rank=rec["min_rank"],
                    data_source=data_source, match_method=rec["match_method"],
                    source_url=rec["source_url"] or source_url, note=rec["note"],
                    operator=operator, updated_at=now))
                report["inserted"] += 1
                continue
            changed = (row.min_score != rec["min_score"] or row.min_rank != rec["min_rank"]
                       or row.batch != rec["batch"])
            if not changed:
                report["unchanged"] += 1
                continue
            s.add(DataChange(dataset="school_lines", year=rec["year"], action="import",
                             entity=f"{rec['province']}/{rec['subject']}/{rec['university']}",
                             field="min_score/min_rank",
                             old_value=f"{row.min_score}/{row.min_rank}",
                             new_value=f"{rec['min_score']}/{rec['min_rank']}",
                             reason=f"导入 {filename}", operator=operator))
            row.min_score = rec["min_score"]
            row.min_rank = rec["min_rank"]
            row.batch = rec["batch"] or row.batch
            row.university_input = rec["university_input"]
            row.match_method = rec["match_method"]
            row.data_source = data_source
            row.source_url = rec["source_url"] or source_url or row.source_url
            row.note = rec["note"] or row.note
            row.operator = operator
            report["updated"] += 1

        if mode == "replace" and records:
            scopes = {(r["year"], r["province"], r["subject"]) for r in records}
            # keep 必须按 (年, 省, 科类) 分开：一个文件可能含多个 scope，
            # 用全局 keep 会让「本 scope 已不存在、但别的 scope 里有」的旧行漏删。
            keep_by_scope: dict[tuple, set] = {}
            for r in records:
                keep_by_scope.setdefault(
                    (r["year"], r["province"], r["subject"]), set()).add(
                    (r["university"], r["group_code"]))
            for year, province, subject in scopes:
                keep = keep_by_scope.get((year, province, subject), set())
                rows = s.scalars(select(SchoolLine).where(
                    SchoolLine.year == year, SchoolLine.province == province,
                    SchoolLine.subject == subject)).all()
                for row in rows:
                    if (row.university, row.group_code) not in keep:
                        s.delete(row)
                        report["deleted"] += 1

    report["data_source"] = data_source
    invalidate_cache()
    return report


# ---------------------------------------------------------------- 查询

def invalidate_cache() -> None:
    _LINES_CACHE.clear()


def lines_for(province: str, subject: str, university: str = None, year: int = None,
              limit: int = 200) -> dict:
    """查询某省/科类的投档线；可按院校过滤。"""
    with session_scope() as s:
        stmt = select(SchoolLine).where(SchoolLine.province == province,
                                        SchoolLine.subject == subject)
        if university:
            stmt = stmt.where(SchoolLine.university == university)
        if year:
            stmt = stmt.where(SchoolLine.year == year)
        rows = s.scalars(stmt.order_by(SchoolLine.year.desc(), SchoolLine.min_rank)
                         .limit(max(1, min(limit, 1000)))).all()
        return {"ok": True, "count": len(rows), "rows": [{
            "year": r.year, "province": r.province, "subject": r.subject, "batch": r.batch,
            "university": r.university, "group_code": r.group_code,
            "min_score": r.min_score, "min_rank": r.min_rank,
            "data_source": r.data_source, "match_method": r.match_method,
            "source_url": r.source_url,
        } for r in rows]}


def coverage() -> dict:
    """导入覆盖概况：哪些年份/省份有院校级数据、共多少行。"""
    with session_scope() as s:
        rows = s.execute(select(SchoolLine.year, SchoolLine.province, SchoolLine.subject,
                                SchoolLine.university)).all()
    by_year: dict[int, dict] = {}
    for year, province, subject, uni in rows:
        node = by_year.setdefault(int(year), {"rows": 0, "provinces": set(), "schools": set()})
        node["rows"] += 1
        node["provinces"].add(province)
        node["schools"].add(uni)
    return {
        "total": len(rows),
        "years": [{"year": y, "rows": v["rows"], "provinces": sorted(v["provinces"]),
                   "schools": len(v["schools"])} for y, v in sorted(by_year.items(), reverse=True)],
    }


def source_counts() -> dict:
    """按 ``data_source`` 统计院校投档线，用于健康上报与前端权威性声明。

    返回各来源行数、覆盖省份（去重，无论来源）、是否有官方数据、整体权威等级。
    当前全部为 ``estimated_real``（掌上高考 2025 真实抓取）；一旦通过管理端
    「校线导入」上传考试院官方表（``data_source=official``），``official`` 计数即上升。
    """
    with session_scope() as s:
        rows = s.execute(select(SchoolLine.data_source, SchoolLine.province)).all()
    counts: dict[str, int] = {}
    provinces: set[str] = set()
    for ds, prov in rows:
        key = ds or "unknown"
        counts[key] = counts.get(key, 0) + 1
        if prov:
            provinces.add(prov)
    official = counts.get("official", 0)
    estimated = counts.get("estimated_real", 0)
    # M07 修复：三态互斥展开（同 verify.py——原短路写法使 mixed 永远不可达）。
    grade = ("official" if (official and not estimated)
             else "mixed" if (official and estimated)
             else "estimated_real")
    return {
        "total": sum(counts.values()),
        "by_source": counts,
        "official": official,
        "estimated_real": estimated,
        "provinces": sorted(provinces),
        "province_count": len(provinces),
        "has_official": bool(official),
        "grade": grade,
        "official_coverage": official_coverage(),
    }


def official_coverage() -> dict:
    """官方行覆盖率（S9-D）：防止把「有几行 official」误读成「该校数据都官方」。

    按「院校 × 专业组」去重统计：official 口径覆盖了多少个专业组，占全部专业组的比例。
    例如 14020 行数据里只有 22 行来自 985/211 官方入门投档，那么 official 覆盖的专业组
    极少，覆盖率应显著低于 100%，核验页据此提示用户「仅极少数院校为考试院官方口径」。
    """
    with session_scope() as s:
        rows = s.execute(
            select(SchoolLine.university, SchoolLine.group_code, SchoolLine.data_source)
        ).all()
    groups: dict[tuple, bool] = {}
    schools: set[str] = set()
    official_schools: set[str] = set()
    for univ, grp, ds in rows:
        key = (univ, grp)
        schools.add(univ)
        is_off = ds == "official"
        # 同一专业组可能同时有 estimated + official；任一官方即算覆盖
        groups[key] = groups.get(key, False) or is_off
        if is_off:
            official_schools.add(univ)
    total_groups = len(groups)
    official_groups = sum(1 for v in groups.values() if v)
    total_schools = len(schools)
    ratio = round(official_groups / total_groups, 4) if total_groups else 0.0
    return {
        "groups": {"official": official_groups, "total": total_groups,
                   "ratio": ratio, "ratio_pct": round(ratio * 100, 1)},
        "schools": {"official": len(official_schools), "total": total_schools,
                    "ratio": round(len(official_schools) / total_schools, 4) if total_schools else 0.0},
    }


def latest_year(province: str, subject: str) -> int | None:
    """该 (省/科类) 校线的最新年份；无数据返回 None。

    M09：推荐/核验链路的跨校位次比较必须钉在单一参考年（S9-B：跨年位次不可直接比），
    调用方以此取参考年再传给 ``map_for``。
    """
    with session_scope() as s:
        v = s.execute(
            select(func.max(SchoolLine.year)).where(
                SchoolLine.province == province, SchoolLine.subject == subject)
        ).scalar()
    return int(v) if v else None


def map_for(province: str, subject: str, names: list[str], year: int = None) -> dict:
    """给推荐用：一次取出某省/科类的院校线，返回 {校名: 记录}。

    同一院校多条记录时按「最新年份 → 官方优先 → 位次最优（数值最小）」挑一条：
    同年同校的 official 行与 estimated_real 行并存时（如层次占位行 vs 抓取行），
    以官方口径优先，避免估算值遮蔽官方值；data_source 透传真实来源。
    """
    if not names:
        return {}
    wanted = set(names)
    with session_scope() as s:
        stmt = select(SchoolLine).where(SchoolLine.province == province,
                                        SchoolLine.subject == subject)
        if year:
            stmt = stmt.where(SchoolLine.year == year)
        rows = s.execute(stmt).scalars().all()
    out: dict[str, dict] = {}
    for r in rows:
        if r.university not in wanted:
            continue
        cur = out.get(r.university)
        cand = {"year": r.year, "min_score": r.min_score, "min_rank": r.min_rank,
                "group_code": r.group_code, "batch": r.batch,
                "data_source": r.data_source or "school_line"}
        # 元组越大越优：年份新 → official 优先 → 位次数值小（门槛低）
        cand_key = (cand["year"], cand["data_source"] == "official", -cand["min_rank"])
        if cur is None or cand_key > (cur["year"], cur["data_source"] == "official",
                                      -cur["min_rank"]):
            out[r.university] = cand
    return out


# ---------------------------------------------------------------- 自托管种子（S6）

# 背景：院校投档线原先只能靠 ``import_crawler_school_lines.py`` 现拉上游公开爬虫仓库
# （1837620622/gaokao-admission-crawler）。那个仓库是第三方开源项目，随时可能下架、
# 改名或被清空——一旦如此，新机器 clone 本仓库后将**无法重建任何校线数据**。
# 解决办法：把已入库的真实数据导出成仓库自带的种子文件并提交入库，
# 新环境无需联网即可经管理端「一键落库」重建；官方数据同样从仓库内的官方文件直接落库。

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_BACKEND_DIR, "data")
# S7-B：种子默认以 gzip 提交（明文体积 7.2MB → 约 1MB），读取时按后缀自动解压；
# 明文路径仅作兼容回退，不再随仓库提交。
SEED_ESTIMATED = os.path.join(DATA_DIR, "school_lines_estimated_real.json.gz")
SEED_ESTIMATED_PLAIN = os.path.join(DATA_DIR, "school_lines_estimated_real.json")
SEED_META = os.path.join(DATA_DIR, "seed.meta.json")
OFFICIAL_ADMISSION = os.path.join(DATA_DIR, "admission_official_2024.json")
# S7-A：官方逐校投档线落地区。运营把各省考试院原表放进来，一键落库即可识别；
# 仓库不预置任何「官方」数据文件，缺 source_url 的行一律拒收（见 validate_official_rows）。
OFFICIAL_DIR = os.path.join(DATA_DIR, "official")
# P2：官方原表留档区。考试院链接经常改版失效，落库成功后把原表字节按 sha256 留档，
# 让「真实性」不依赖外链存活——与 S6 收编 estimated 种子是同一个自持思路。
OFFICIAL_ARCHIVE_DIR = os.path.join(OFFICIAL_DIR, "archive")

_URL_RE = re.compile(r"https?://[^\s；;，,）)]+")

# 看起来像省级招生考试机构的域名片段（软校验：不在其中只告警，不阻断）
_OFFICIAL_HOST_HINTS = (
    "gov.cn", "edu.cn", "eea.", "zsks", "zk.", "ksy.", "jseea", "sceea", "haeea",
    "eeafj", "ahzsks", "hneeb", "cqksy", "sdzk", "hebeea", "ganseea", "gseea",
)


def _seed_open_write(path: str):
    if path.endswith(".gz"):
        import gzip
        return gzip.open(path, "wt", encoding="utf-8")
    return open(path, "w", encoding="utf-8")


def _seed_open_read(path: str):
    if path.endswith(".gz"):
        import gzip
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _resolve_seed() -> str:
    """定位种子文件：优先模块常量（测试可覆盖），回退明文路径。"""
    if os.path.exists(SEED_ESTIMATED):
        return SEED_ESTIMATED
    if os.path.exists(SEED_ESTIMATED_PLAIN):
        return SEED_ESTIMATED_PLAIN
    return SEED_ESTIMATED


def sha256_of(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(raw: bytes) -> str:
    """内存字节流的 sha256（S8-A：给上传的官方原表留校验和）。"""
    import hashlib
    return hashlib.sha256(raw or b"").hexdigest()


def read_seed(path: str | None = None) -> dict:
    """读取种子（自动识别 gzip），损坏时抛错由调用方处理。"""
    path = path or _resolve_seed()
    with _seed_open_read(path) as f:
        return json.load(f)


def seed_meta() -> dict:
    """种子校验和清单（S7-B）。缺失时返回 {"exists": False}。"""
    if not os.path.exists(SEED_META):
        return {"exists": False}
    try:
        with open(SEED_META, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return {"exists": False}
    return {"exists": True, **meta}


def verify_seed(path: str | None = None) -> dict:
    """校验种子完整性：文件在、JSON 可解析、sha256 与清单一致。"""
    path = path or _resolve_seed()
    out = {"path": path, "exists": os.path.exists(path), "rows": 0,
           "sha256": "", "size_bytes": 0, "ok": False, "errors": []}
    if not out["exists"]:
        out["errors"].append("种子文件缺失")
        return out
    out["size_bytes"] = os.path.getsize(path)
    try:
        out["sha256"] = sha256_of(path)
        out["rows"] = len(read_seed(path).get("rows") or [])
    except (OSError, ValueError) as exc:
        out["errors"].append(f"种子损坏：{exc}")
        return out
    # 只有「仓库正式种子」才与 seed.meta.json 比对，临时导出文件不做该比对
    if os.path.abspath(path) == os.path.abspath(SEED_ESTIMATED):
        meta = seed_meta()
        if meta.get("exists") and meta.get("sha256") and meta["sha256"] != out["sha256"]:
            out["errors"].append("校验和与 seed.meta.json 不一致，请重新导出")
    out["ok"] = not out["errors"]
    return out


def export_seed(path: str = SEED_ESTIMATED, data_source: str = "estimated_real",
                write_manifest: bool | None = None, year: int | None = None) -> dict:
    """把库里的院校投档线导出成仓库自带的种子文件（默认只导真实抓取的 estimated_real）。

    导出的种子让仓库自持一份可复现的数据副本，摆脱对上游爬虫仓库的运行时依赖。
    支持 gzip（路径以 ``.gz`` 结尾时自动压缩）与按年份筛选（``year``）。
    """
    with session_scope() as s:
        stmt = select(SchoolLine)
        if data_source:
            stmt = stmt.where(SchoolLine.data_source == data_source)
        if year:
            stmt = stmt.where(SchoolLine.year == year)
        rows = s.scalars(stmt).all()
        meta = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_source": data_source or "all",
            "year": year,
            "rows": len(rows),
            "note": "由 export_seed 从已入库数据导出；用于摆脱对上游爬虫仓库的运行时依赖。",
        }
        payload = {
            "meta": meta,
            "rows": [{
                "year": r.year, "province": r.province, "subject": r.subject,
                "batch": r.batch, "university": r.university,
                "university_input": r.university_input, "group_code": r.group_code,
                "min_score": r.min_score, "min_rank": r.min_rank,
                "data_source": r.data_source, "match_method": r.match_method,
                "source_url": r.source_url, "note": r.note,
            } for r in rows],
        }
    if path:
        with _seed_open_write(path) as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        # S7-B：默认只在导出「仓库种子」时更新校验和清单，避免临时导出覆盖正式清单
        should_manifest = write_manifest if write_manifest is not None else (
            os.path.abspath(path) == os.path.abspath(SEED_ESTIMATED))
        if should_manifest:
            try:
                manifest = {
                    "file": os.path.basename(path),
                    "data_source": data_source or "all",
                    "rows": meta["rows"],
                    "generated_at": meta["generated_at"],
                    "size_bytes": os.path.getsize(path),
                    "sha256": sha256_of(path),
                    "compressed": path.endswith(".gz"),
                }
                with open(SEED_META, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
                meta["sha256"] = manifest["sha256"]
                meta["size_bytes"] = manifest["size_bytes"]
                meta["compressed"] = manifest["compressed"]
            except OSError:  # 清单写失败不阻塞导出
                pass
    return meta


def official_seed_rows() -> list[dict]:
    """从官方录取文件取出各省考试院发布的「985/211 入门投档」作为 ``official`` 校线。

    ``admission_official_2024.json`` 的 ``school_tier_lines`` 是各省考试院公布的该省
    该科类普通类本科批 985/211 最低投档线（含入门院校），属真实官方口径，可直接落库。

    ``group_code`` 用层次（985/211）占位：既避免与逐专业组的 ``estimated_real`` 行
    撞唯一键，也保留了「这是层次入门线而非某个专业组」的语义。
    """
    if not os.path.exists(OFFICIAL_ADMISSION):
        return []
    with open(OFFICIAL_ADMISSION, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.get("meta") or {}
    year = int(meta.get("year") or 2024)
    sources = meta.get("sources") or {}
    out: list[dict] = []
    for province, by_subject in (doc.get("school_tier_lines") or {}).items():
        match_url = _URL_RE.search(sources.get(province, "") or "")
        source_url = match_url.group(0) if match_url else ""
        for subject, tiers in (by_subject or {}).items():
            for tier, item in (tiers or {}).items():
                item = item or {}
                school = item.get("school") or ""
                if not school:
                    continue
                canonical, method, sim = match_university(school)
                if not canonical:
                    continue
                out.append({
                    "year": year, "province": province, "subject": subject,
                    "batch": "普通类本科批",
                    "university": canonical, "university_input": school[:128],
                    "group_code": tier,
                    "min_score": int(item.get("score") or 0),
                    "min_rank": int(item.get("rank") or 0),
                    "data_source": "official", "match_method": method, "match_score": sim,
                    "source_url": source_url,
                    "note": f"省考试院官方{tier}入门投档（普通类本科批）：{item.get('line', '')}；"
                            f"入门院校={school}",
                })
    return out


# ---------------------------------------------------------------- 官方逐校投档线落地区（S7-A）

# S6 的官方数据只到「985/211 层次入门线」（6 省 22 行）。S7-A 把官方通道扩到
# **逐校逐专业组**：运营把各省考试院发布的投档原表放进 backend/data/official/，
# 或经管理端上传（必须带官方来源链接），即可落为 school_lines 的 official 行。
#
# 诚实边界：仓库**不预置**任何逐校官方数据文件（我们手上没有可核实的官方原表，
# 也不允许把抓取数据标成官方）。落地区只是通道；缺 source_url 的行一律拒收，
# 来源域名不像考试院机构时只告警并留痕，由运营人工复核。

_OFFICIAL_FIELD_KEYS = {
    "university": ("university", "院校", "院校名称", "学校", "school"),
    "province": ("province", "省份", "生源地"),
    "subject": ("subject", "科类", "选科"),
    "year": ("year", "年份"),
    "min_score": ("min_score", "最低分", "投档分", "score"),
    "min_rank": ("min_rank", "最低位次", "位次", "rank"),
    "group_code": ("group_code", "专业组", "院校专业组"),
    "batch": ("batch", "批次", "录取批次"),
    "source_url": ("source_url", "来源", "链接", "来源链接"),
    "note": ("note", "备注", "说明"),
    "source_org": ("source_org", "来源机构", "发布机构"),
}


def _pick(row: dict, field: str):
    for key in _OFFICIAL_FIELD_KEYS.get(field, (field,)):
        v = row.get(key)
        if v not in (None, ""):
            return v
    return None


def _official_files(directory: str | None = None) -> list[str]:
    d = directory or OFFICIAL_DIR
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        low = name.lower()
        if name.startswith(".") or low.endswith((".md", ".meta.json")):
            continue
        if low.endswith((".json", ".csv")):
            out.append(os.path.join(d, name))
    return out


def _official_rows_from_file(path: str) -> tuple[list[dict], dict]:
    """解析官方原表文件 → (行, meta)。meta 可带 source_url / 年份 / 省份 等默认值。"""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict):
            return list(doc.get("rows") or []), dict(doc.get("meta") or {})
        return list(doc or []), {}
    with open(path, "rb") as f:
        parsed = parse_table(f.read(), path)
    if not parsed.get("ok"):
        return [], {"error": parsed.get("error", "表头无法识别")}
    mapping = parsed["mapping"]
    rows = []
    for r in parsed["rows"]:
        rows.append({field: (r[idx] if idx < len(r) else None) for field, idx in mapping.items()})
    return rows, {}


def validate_official_rows(rows: list[dict], defaults: dict | None = None) -> dict:
    """官方行强校验（S7-A）。

    ``official`` 是可信度最高的标签，因此比普通导入更严：
    省份/科类/年份/分数位次越界、校名匹配不上教育部名单、**缺官方来源链接**
    一律拒收并给出原因——宁可少落，也不能把来路不明的行标成官方。
    """
    defaults = defaults or {}
    accepted: list[dict] = []
    rejected: list[dict] = []
    for i, raw in enumerate(rows or []):
        row = raw if isinstance(raw, dict) else {}
        university = str(_pick(row, "university") or "").strip()
        province = _norm_province(str(_pick(row, "province") or defaults.get("province") or ""))
        subject = _norm_subject(str(_pick(row, "subject") or defaults.get("subject") or ""))
        year = _to_int(_pick(row, "year")) or _to_int(defaults.get("year")) or 0
        score = _to_int(_pick(row, "min_score"))
        rank = _to_int(_pick(row, "min_rank"))
        group_code = str(_pick(row, "group_code") or "").strip()
        batch = str(_pick(row, "batch") or defaults.get("batch") or "普通类本科批").strip()
        source_url = str(_pick(row, "source_url") or defaults.get("source_url") or "").strip()
        source_org = str(_pick(row, "source_org") or defaults.get("source_org") or "").strip()

        reasons: list[str] = []
        if not university:
            reasons.append("院校名称为空")
        if province not in PROVINCES:
            reasons.append(f"省份无法识别：{province or '空'}")
        if not subject:
            reasons.append("科类为空")
        if not (2000 <= int(year or 0) <= 2100):
            reasons.append(f"年份异常：{year}")
        if score is None and rank is None:
            reasons.append("最低分/最低位次 全缺")
        if score is not None and not (0 < score <= MAX_SCORE):
            reasons.append(f"最低分越界：{score}")
        if rank is not None and not (0 < rank <= MAX_RANK):
            reasons.append(f"位次越界：{rank}")
        if not source_url.startswith(("http://", "https://")):
            reasons.append("缺少官方来源链接 source_url（官方口径必须可回溯）")

        canonical = method = None
        if university and not reasons:
            canonical, method, _sim = match_university(university)
            if not canonical:
                reasons.append(f"院校未匹配教育部名单：{university}")
        if reasons:
            rejected.append({"index": i, "university": university, "reasons": reasons})
            continue

        host_m = re.search(r"https?://([^/]+)", source_url)
        host = host_m.group(1) if host_m else ""
        trusted = any(h in host for h in _OFFICIAL_HOST_HINTS)
        note = str(_pick(row, "note") or "")
        if not trusted:
            note = (note + "；" if note else "") + f"来源域名 {host} 非考试院机构，需人工复核"
        accepted.append({
            "year": int(year), "province": province, "subject": subject,
            "batch": batch, "university": canonical, "university_input": university[:128],
            "group_code": group_code or "官方投档",
            "min_score": int(score or 0), "min_rank": int(rank or 0),
            "data_source": "official", "match_method": method or "exact",
            "source_url": source_url,
            "note": note or (f"官方原表落库（{source_org or '省考试院'}）"),
            "trusted_host": trusted,
        })
    return {
        "total": len(rows or []), "accepted": accepted, "rejected": rejected,
        "provenance_warnings": [r for r in accepted if not r["trusted_host"]],
    }


def official_landing_rows(directory: str | None = None) -> dict:
    """扫描落地区（只读）→ 可落库的官方逐校行 + 拒收明细。"""
    d = directory or OFFICIAL_DIR
    files = _official_files(d)
    accepted: list[dict] = []
    rejected: list[dict] = []
    per_file: list[dict] = []
    for path in files:
        rows, meta = _official_rows_from_file(path)
        defaults = {k: meta[k] for k in ("year", "province", "subject", "batch",
                                         "source_url", "source_org") if meta.get(k)}
        res = validate_official_rows(rows, defaults)
        accepted.extend(res["accepted"])
        for item in res["rejected"]:
            item["file"] = os.path.basename(path)
        rejected.extend(res["rejected"])
        per_file.append({"file": os.path.basename(path), "total": res["total"],
                         "accepted": len(res["accepted"]), "rejected": len(res["rejected"]),
                         "error": meta.get("error", "")})
    return {"dir": d, "dir_exists": os.path.isdir(d), "files": per_file,
            "accepted": accepted, "rejected": rejected,
            "accepted_count": len(accepted), "rejected_count": len(rejected),
            "provenance_warnings": len([r for r in accepted if not r["trusted_host"]])}


# ---------------------------------------------------------------- 官方溯源登记（S8-A）
# 每个落过库的官方文件留一条台账：文件名 / 校验和 / 省 / 年 / 科类 / 来源链接 / 行数。
# 目的：official 是最高可信度标签，任何一行官方数据都必须能追到「哪个文件、哪条链接」。
OFFICIAL_REGISTRY = os.path.join(OFFICIAL_DIR, "sources.json")


def official_registry() -> dict:
    """官方文件溯源台账（只读）。"""
    items: list[dict] = []
    if os.path.exists(OFFICIAL_REGISTRY):
        try:
            with open(OFFICIAL_REGISTRY, encoding="utf-8") as f:
                doc = json.load(f)
            items = list(doc.get("files") or [])
        except (OSError, ValueError):
            items = []
    return {"path": OFFICIAL_REGISTRY, "files": items, "count": len(items),
            "rows": sum(int(it.get("rows") or 0) for it in items),
            "provinces": sorted({it.get("province") for it in items if it.get("province")}),
            "sources": sorted({it.get("source_url") for it in items if it.get("source_url")})}


def record_official_source(filename: str, province: str = "", year: int | None = None,
                           subject: str = "", source_url: str = "", source_org: str = "",
                           rows: int = 0, rejected: int = 0, sha256: str = "",
                           archive: str = "", operator: str = "system") -> dict:
    """登记一条官方文件溯源（按文件名去重，重复登记只更新）。"""
    reg = official_registry()
    entry = {
        "file": filename, "province": province, "year": year, "subject": subject,
        "source_url": source_url, "source_org": source_org, "rows": int(rows or 0),
        "rejected": int(rejected or 0), "sha256": sha256, "archive": archive,
        "operator": operator,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    items = [it for it in reg["files"] if it.get("file") != filename]
    items.append(entry)
    items.sort(key=lambda it: str(it.get("file") or ""))
    try:
        os.makedirs(os.path.dirname(OFFICIAL_REGISTRY), exist_ok=True)
        with open(OFFICIAL_REGISTRY, "w", encoding="utf-8") as f:
            json.dump({"updated_at": entry["imported_at"], "files": items},
                      f, ensure_ascii=False, indent=2)
    except OSError:  # 台账写失败不阻断落库，但要在返回值里说实话
        return {"ok": False, "error": "溯源台账写入失败", "entry": entry}
    return {"ok": True, "entry": entry, "count": len(items)}


def parse_official_table(raw: bytes, filename: str = "",
                         defaults: dict | None = None) -> dict:
    """把省考试院原表（CSV / XLSX / JSON）解析成可校验的官方行（S8-A）。

    与 ``parse_table`` 的区别：这里直接用 ``normalize_row`` 产结构化记录（含校名匹配），
    并把文件级默认值（年 / 省 / 科类 / 批次 / 来源链接）灌进去，供 ``validate_official_rows``
    做强校验。
    """
    defaults = dict(defaults or {})
    lower = (filename or "").lower()
    if lower.endswith(".json"):
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            doc = json.loads(raw.decode("utf-8-sig", errors="replace"))
        rows = list(doc.get("rows") if isinstance(doc, dict) else doc) or []
        for k in ("year", "province", "subject", "batch", "source_url", "source_org"):
            if isinstance(doc, dict) and doc.get(k) and not defaults.get(k):
                defaults[k] = doc[k]
        if isinstance(doc, dict) and isinstance(doc.get("meta"), dict):
            for k in ("year", "province", "subject", "batch", "source_url", "source_org"):
                if doc["meta"].get(k) and not defaults.get(k):
                    defaults[k] = doc["meta"][k]
        return {"ok": True, "rows": rows, "defaults": defaults,
                "parsed": len(rows), "format": "json"}
    try:
        parsed = parse_table(raw, filename)
    except RuntimeError as exc:  # 旧版 .xls 等
        return {"ok": False, "error": str(exc), "rows": [], "defaults": defaults}
    if not parsed.get("ok"):
        return {"ok": False, "error": parsed.get("error", "表头无法识别"),
                "detected_headers": parsed.get("detected_headers", []),
                "rows": [], "defaults": defaults}
    mapping = parsed["mapping"]
    records = []
    for r in parsed["rows"]:
        rec = normalize_row(r, mapping, defaults)
        rec["source_url"] = rec.get("source_url") or str(defaults.get("source_url") or "")
        records.append(rec)
    return {"ok": True, "rows": records, "defaults": defaults,
            "parsed": len(records), "header": parsed.get("header", []),
            "format": "xlsx" if lower.endswith((".xlsx", ".xlsm")) else "csv"}


def import_official_table(raw: bytes, filename: str = "", defaults: dict | None = None,
                          dry_run: bool = True, operator: str = "admin",
                          register: bool = True, archive: bool = True) -> dict:
    """官方原表一键落库（S8-A）：解析 → 强校验 → 幂等写 official → 写溯源台账。

    ``dry_run=True`` 只报「可落库 / 拒收」明细，不写库也不登记。
    P2 增补：落库成功后把原表字节按 sha256 留档进 ``data/official/archive/``，
    考试院链接失效后仍可复核（``archive=False`` 可关闭）。
    """
    parsed = parse_official_table(raw, filename, defaults)
    if not parsed.get("ok"):
        return {"ok": False, "error": parsed.get("error", "解析失败"),
                "detected_headers": parsed.get("detected_headers", []),
                "file": filename, "parsed": 0}
    report = import_official(rows=parsed["rows"], defaults=parsed["defaults"],
                             dry_run=dry_run, operator=operator)
    report["file"] = filename
    report["parsed"] = parsed["parsed"]
    report["format"] = parsed.get("format", "")
    if register and not dry_run and report.get("ok") and report.get("inserted", 0) + report.get("updated", 0) > 0:
        digest = sha256_bytes(raw)
        archive_path = archive_official_table(raw, filename, digest) if archive else ""
        rec = record_official_source(
            filename=filename or "upload", province=parsed["defaults"].get("province", ""),
            year=parsed["defaults"].get("year"), subject=parsed["defaults"].get("subject", ""),
            source_url=parsed["defaults"].get("source_url", ""),
            source_org=parsed["defaults"].get("source_org", ""),
            rows=report.get("accepted", 0), rejected=report.get("rejected", 0),
            sha256=digest, archive=archive_path, operator=operator)
        report["registry"] = rec
        if archive_path:
            report["archive"] = archive_path
    return report


def archive_official_table(raw: bytes, filename: str, sha256: str = "") -> str:
    """把官方原表字节留档（P2）：按 sha256 前缀命名，重复落库不重复写。

    返回相对 ``data/`` 的存档路径；写失败不阻断落库，返回空串并在调用方如实上报。
    """
    if not raw:
        return ""
    digest = sha256 or sha256_bytes(raw)
    safe = os.path.basename(filename or "upload").replace("\\", "_") or "upload"
    try:
        os.makedirs(OFFICIAL_ARCHIVE_DIR, exist_ok=True)
        dst = os.path.join(OFFICIAL_ARCHIVE_DIR, f"{digest[:16]}-{safe}")
        if not os.path.exists(dst):
            with open(dst, "wb") as f:
                f.write(raw)
        return os.path.relpath(dst, DATA_DIR)
    except OSError:
        return ""


def import_official(rows: list[dict], defaults: dict | None = None, dry_run: bool = True,
                    operator: str = "admin") -> dict:
    """官方原表一键落库（S7-A）：强校验 → 幂等写 ``data_source=official``。

    ``dry_run=True`` 只报「可落库 / 拒收」明细，不写库。
    P2 增补：对可落库行做「分数 ↔ 位次」交叉校验（用当年一分一段表反查），
    偏差超阈值的行把疑点写进行备注（commit 时随行落库，dry-run 时仅供预览）。
    """
    res = validate_official_rows(rows, defaults)
    from services import data_quality as DQ  # 局部导入避免环
    cross = DQ.annotate_cross_check(res["accepted"])
    report = {
        "ok": True, "dry_run": dry_run, "operator": operator,
        "total": res["total"], "accepted": len(res["accepted"]), "rejected": len(res["rejected"]),
        "inserted": 0, "updated": 0, "unchanged": 0,
        "provenance_warnings": len(res["provenance_warnings"]),
        "rejected_samples": res["rejected"][:20],
        "cross_check": {"checked": cross["checked"], "warnings": len(cross["warnings"]),
                        "samples": cross["warnings"][:20]},
    }
    if dry_run or not res["accepted"]:
        return report
    _upsert(res["accepted"], operator, report)
    invalidate_cache()
    return report


def _upsert(records: list[dict], operator: str, report: dict) -> None:
    """按 (年, 省, 科类, 院校, 专业组/层次) 幂等写库，统计写进 ``report``。"""
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        for rec in records:
            row = s.scalar(select(SchoolLine).where(
                SchoolLine.year == rec["year"], SchoolLine.province == rec["province"],
                SchoolLine.subject == rec["subject"], SchoolLine.university == rec["university"],
                SchoolLine.group_code == rec["group_code"]))
            if row is None:
                s.add(SchoolLine(
                    year=rec["year"], province=rec["province"], subject=rec["subject"],
                    batch=rec.get("batch", ""), university=rec["university"],
                    university_input=rec.get("university_input", ""),
                    group_code=rec.get("group_code", ""),
                    min_score=rec["min_score"], min_rank=rec["min_rank"],
                    data_source=rec["data_source"], match_method=rec.get("match_method", "exact"),
                    source_url=rec.get("source_url", ""), note=rec.get("note", ""),
                    operator=operator, updated_at=now))
                report["inserted"] += 1
                continue
            changed = (row.min_score != rec["min_score"] or row.min_rank != rec["min_rank"]
                       or row.batch != rec.get("batch", ""))
            if not changed:
                report["unchanged"] += 1
                continue
            s.add(DataChange(dataset="school_lines", year=rec["year"], action="import",
                             entity=f"{rec['province']}/{rec['subject']}/{rec['university']}",
                             field="min_score/min_rank",
                             old_value=f"{row.min_score}/{row.min_rank}",
                             new_value=f"{rec['min_score']}/{rec['min_rank']}",
                             reason="一键落库（自托管种子）", operator=operator))
            row.min_score = rec["min_score"]
            row.min_rank = rec["min_rank"]
            row.batch = rec.get("batch", "") or row.batch
            row.university_input = rec.get("university_input", "")
            row.match_method = rec.get("match_method", row.match_method)
            row.data_source = rec["data_source"]
            row.source_url = rec.get("source_url", "") or row.source_url
            row.note = rec.get("note", "") or row.note
            row.operator = operator
            report["updated"] += 1


def seed_status() -> dict:
    """自托管种子的可用性与完整性（供管理端「一键落库」展示，只读不写库）。

    S7-B 增补：sha256 校验和、体积、是否压缩，以及「种子行数 vs 库内行数」的一致性提示。
    """
    path = _resolve_seed()
    exists = os.path.exists(path)
    rows, checksum, size = 0, "", 0
    if exists:
        try:
            rows = len(read_seed(path).get("rows") or [])
        except Exception:  # 种子损坏时不阻塞页面
            rows = 0
        try:
            checksum, size = sha256_of(path), os.path.getsize(path)
        except OSError:
            pass
    official = official_seed_rows()
    landing = official_landing_rows()
    db_rows = source_counts().get("estimated_real", 0)
    return {
        "estimated": {"path": path, "exists": exists, "rows": rows,
                      "data_source": "estimated_real", "sha256": checksum,
                      "size_bytes": size, "compressed": path.endswith(".gz"),
                      "manifest": seed_meta(), "db_rows": db_rows,
                      "consistent": bool(exists and rows and rows == db_rows)},
        "official": {"path": OFFICIAL_ADMISSION, "exists": os.path.exists(OFFICIAL_ADMISSION),
                     "rows": len(official), "data_source": "official"},
        "official_dir": {"path": landing["dir"], "exists": landing["dir_exists"],
                         "files": landing["files"], "rows": landing["accepted_count"],
                         "rejected": landing["rejected_count"],
                         "provenance_warnings": landing["provenance_warnings"]},
        "total_seed_rows": rows + len(official) + landing["accepted_count"],
    }


def import_seed(commit: bool = True, operator: str = "system",
                include: list[str] | None = None) -> dict:
    """一键落库：把仓库自带的种子数据写进 ``school_lines``（幂等，无需联网）。

    - ``estimated``：``school_lines_estimated_real.json``（真实抓取快照，标 estimated_real）
    - ``official``：官方文件的 985/211 入门投档（省考试院官方口径，标 official）

    两者都按 (年, 省, 科类, 院校, 专业组/层次) 幂等 upsert：重复执行只改变化的行，
    不会重复插入。``commit=False`` 时只返回「可落库行数」，不写库。
    """
    include = include or ["estimated", "official"]
    report = {
        "ok": True, "dry_run": not commit, "operator": operator,
        "estimated": {"inserted": 0, "updated": 0, "unchanged": 0, "available": 0, "skipped": False},
        "official": {"inserted": 0, "updated": 0, "unchanged": 0, "available": 0, "skipped": False},
        "inserted": 0, "updated": 0, "unchanged": 0,
    }

    est_records: list[dict] = []
    if "estimated" in include:
        path = _resolve_seed()
        if os.path.exists(path):
            est_records = read_seed(path).get("rows") or []
        else:
            report["estimated"]["skipped"] = True
    report["estimated"]["available"] = len(est_records)

    off_records: list[dict] = []
    if "official" in include:
        off_records += official_seed_rows()
        landing = official_landing_rows()          # S7-A：官方落地区里的逐校原表
        off_records += landing["accepted"]
        report["official"]["landing"] = {
            "dir": landing["dir"], "files": landing["files"],
            "accepted": landing["accepted_count"], "rejected": landing["rejected_count"],
            "provenance_warnings": landing["provenance_warnings"],
            "rejected_samples": landing["rejected"][:20],
        }
    report["official"]["available"] = len(off_records)

    if not commit:
        return report

    _upsert(est_records, operator, report["estimated"])
    _upsert(off_records, operator, report["official"])
    for part in ("estimated", "official"):
        for key in ("inserted", "updated", "unchanged"):
            report[key] += report[part][key]
    invalidate_cache()
    return report
