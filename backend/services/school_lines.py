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

from sqlalchemy import select

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
    "min_score": ["最低分", "投档分", "最低投档分", "院校最低分", "最低录取分", "投档线", "最低分数线", "分数"],
    "min_rank": ["最低位次", "位次", "最低排名", "排名", "最低位次(名次)", "最低分位次", "位次号"],
    "group_code": ["专业组", "院校专业组", "专业组代码", "专业组号", "组别", "科类代码"],
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
    grade = "official" if official else ("mixed" if (official and estimated) else "estimated_real")
    return {
        "total": sum(counts.values()),
        "by_source": counts,
        "official": official,
        "estimated_real": estimated,
        "provinces": sorted(provinces),
        "province_count": len(provinces),
        "has_official": bool(official),
        "grade": grade,
    }


def map_for(province: str, subject: str, names: list[str], year: int = None) -> dict:
    """给推荐用：一次取出某省/科类的院校线，返回 {校名: 记录}。

    同一院校多年数据时取「最新年份、位次最优（数值最小）」的一条。
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
                "group_code": r.group_code, "batch": r.batch, "data_source": "school_line"}
        if cur is None or (cand["year"], -cand["min_rank"]) > (cur["year"], -cur["min_rank"]):
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
SEED_ESTIMATED = os.path.join(DATA_DIR, "school_lines_estimated_real.json")
OFFICIAL_ADMISSION = os.path.join(DATA_DIR, "admission_official_2024.json")

_URL_RE = re.compile(r"https?://[^\s；;，,）)]+")


def export_seed(path: str = SEED_ESTIMATED, data_source: str = "estimated_real") -> dict:
    """把库里的院校投档线导出成仓库自带的种子文件（默认只导真实抓取的 estimated_real）。

    导出的种子让仓库自持一份可复现的数据副本，摆脱对上游爬虫仓库的运行时依赖。
    """
    with session_scope() as s:
        stmt = select(SchoolLine)
        if data_source:
            stmt = stmt.where(SchoolLine.data_source == data_source)
        rows = s.scalars(stmt).all()
        meta = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_source": data_source or "all",
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
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
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
    """自托管种子的可用性（供管理端「一键落库」展示，只读不写库）。"""
    exists = os.path.exists(SEED_ESTIMATED)
    rows = 0
    if exists:
        try:
            with open(SEED_ESTIMATED, encoding="utf-8") as f:
                rows = len(json.load(f).get("rows") or [])
        except Exception:  # 种子损坏时不阻塞页面
            rows = 0
    official = official_seed_rows()
    return {
        "estimated": {"path": SEED_ESTIMATED, "exists": exists, "rows": rows,
                      "data_source": "estimated_real"},
        "official": {"path": OFFICIAL_ADMISSION, "exists": os.path.exists(OFFICIAL_ADMISSION),
                     "rows": len(official), "data_source": "official"},
        "total_seed_rows": rows + len(official),
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
        if os.path.exists(SEED_ESTIMATED):
            with open(SEED_ESTIMATED, encoding="utf-8") as f:
                est_records = json.load(f).get("rows") or []
        else:
            report["estimated"]["skipped"] = True
    report["estimated"]["available"] = len(est_records)

    off_records = official_seed_rows() if "official" in include else []
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
