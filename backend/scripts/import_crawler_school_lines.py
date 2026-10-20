"""真实院校投档线导入（S2）：从公开爬虫仓库拉取掌上高考 2025 真实录取记录。

数据来源（真实、可核验、可点击）
--------------------------------
- 原始站点：掌上高考 gaokao.cn（2025 真实录取记录）
- 整理仓库：github.com/1837620622/gaokao-admission-crawler（MIT，公开）
- 每条记录在本表 ``school_lines`` 的 ``source_url`` 直接指向该院校的原始 JSON 文件，
  可在前端「查看原始数据」一键打开核验——满足「原始数据点击可达」。

设计要点
--------
- ``data_source='estimated_real'``：区分于纯估算基线，表明这是真实抓取但非考试院官方发布。
- 校名与教育部 2868 所名单匹配（复用 services.school_lines.match_university）。
- 仅保留带省/科类/位次的「院校专业组投档线」记录；缺省省/科类的专业级记录（只有 ID）
  无法可靠映射到省/科类，跳过并在报告中列出，绝不编造省份。
- 幂等：同一 (年,省,科类,院校,专业组) 重复导入只更新。
- 不猜数据：匹配不上的院校跳过并计入 unmatched。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:  # 保证中文能正常打印（部分环境 stdout 默认 ascii）
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from sqlalchemy import select

from db.database import session_scope
from db.models import DataChange, SchoolLine
from services.school_lines import PROVINCES, match_university, norm_text

CRAWLER_REPO = "1837620622/gaokao-admission-crawler"
CRAWLER_API = f"https://api.github.com/repos/{CRAWLER_REPO}/git/trees/main?recursive=1"
RAW_BASE = f"https://raw.githubusercontent.com/{CRAWLER_REPO}/main/"

# 科类归一（旧高考 理科≈物理类、文科≈历史类）
_SUBJ_MAP = {"理科": "物理类", "文科": "历史类", "综合": "综合",
             "物理类": "物理类", "历史类": "历史类"}


def _http_text(url: str, timeout: int = 60, retries: int = 4) -> str:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "xuefeng-importer/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001  (502 等代理抖动，重试即可)
            last = e
            if attempt < retries - 1:
                import time
                time.sleep(2 + attempt * 2)
    raise last or RuntimeError("network")


def fetch_tree(cache_path: str) -> list[dict]:
    if os.path.exists(cache_path):
        tree = json.load(open(cache_path, encoding="utf-8"))
    else:
        tree = json.loads(_http_text(CRAWLER_API))
        json.dump(tree, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    return [x for x in tree.get("tree", []) if x["path"].startswith("gaokao_data/") and x["path"].endswith(".json")]


def build_name_map(tree: list[dict]) -> dict[str, str]:
    """爬虫文件名 '00030_北京工业大学.json' → 校名 → 路径。"""
    out: dict[str, str] = {}
    for x in tree:
        name = os.path.basename(x["path"])
        if name.endswith(".json") and "_" in name:
            school = name[:-5].split("_", 1)[1]
            out[norm_text(school)] = x["path"]
    return out


def target_schools() -> list[str]:
    """全部 985/211 + 分层抽样普通本科（每省 1 所），保证层次与地域覆盖。"""
    from services import admission as A

    elite = A._load_universities().get("universities", [])
    elite_names = [u["name"] for u in elite if u.get("is_985") or u.get("is_211")]
    national = A._load_national().get("universities", [])
    elite_set = set(elite_names)
    by_province: dict[str, list[str]] = {}
    for u in national:
        if u.get("name") in elite_set:
            continue
        if u.get("level") != "本科":
            continue
        by_province.setdefault(u.get("province", ""), []).append(u["name"])
    sampled = []
    for prov, names in by_province.items():
        sampled.append(names[0])
    # 限制抽样规模，避免导入过慢
    sampled = sampled[:40]
    return list(dict.fromkeys(elite_names + sampled))


def _to_int(v):
    if isinstance(v, int):
        return v
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in {"", "-", "—", "—", "/", "无", "nan", "None"}:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_school_json(text: str, school_path: str) -> tuple[list[dict], int]:
    """解析单校 JSON，返回 (可用记录列表, 跳过的有名无省/科类数)。"""
    d = json.loads(text)
    recs = d.get("records", [])
    out, skipped = [], 0
    school_level = d.get("level", "")
    school_prov = d.get("province", "")
    for r in recs:
        prov = r.get("local_province_name")
        subj_raw = r.get("local_type_name")
        if prov not in PROVINCES or subj_raw not in _SUBJ_MAP:
            if r.get("sp_name"):
                skipped += 1
            continue
        rank = _to_int(r.get("min_section"))
        score = _to_int(r.get("min"))
        if not rank or rank <= 0 or not score or score <= 0:
            continue
        subj = _SUBJ_MAP[subj_raw]
        out.append({
            "year": int(d.get("year") or 2025),
            "province": prov,
            "subject": subj,
            "batch": norm_text(r.get("local_batch_name") or ""),
            "university_input": d.get("name", ""),
            "group_code": norm_text(str(r.get("special_group") or r.get("sg_name") or "")),
            "min_score": score,
            "min_rank": rank,
            "note": f"掌上高考2025 专业组投档线；选科={r.get('sg_info','') or '—'}；"
                    f"院校层次={school_level}；院校所在省={school_prov}；"
                    f"专业组={r.get('sg_name','') or '—'}"
                    + (f"；专业={r.get('sp_name')}" if r.get("sp_name") else ""),
            "source_url": RAW_BASE + school_path,
        })
    return out, skipped


def import_all(commit: bool, max_workers: int = 6, only: list[str] | None = None) -> dict:
    tree = fetch_tree("/tmp/crawler_tree.json")
    name_map = build_name_map(tree)
    targets = target_schools()
    if only:  # 仅重试指定院校（用于补齐 502 等瞬断）
        targets = [t for t in targets if t in only]
    matched = [(n, name_map[norm_text(n)]) for n in targets if norm_text(n) in name_map]
    unmatched = [n for n in targets if norm_text(n) not in name_map]

    report = {"total_targets": len(targets), "matched": len(matched), "unmatched": unmatched,
              "schools_ok": 0, "schools_failed": [], "rows_parsed": 0, "skipped_major": 0,
              "inserted": 0, "updated": 0, "unchanged": 0, "samples": []}

    def _fetch_one(item):
        name, path = item
        try:
            url = RAW_BASE + urllib.parse.quote(path)
            text = _http_text(url, timeout=90)
            recs, skipped = parse_school_json(text, path)
            return name, recs, skipped, None
        except Exception as e:  # noqa: BLE001
            return name, [], 0, f"{type(e).__name__}: {e}"

    # 先逐校解析（网络），再统一落库
    parsed: list[tuple] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_one, it): it for it in matched}
        for f in as_completed(futs):
            name, recs, skipped, err = f.result()
            if err:
                report["schools_failed"].append({"school": name, "error": err})
                continue
            report["schools_ok"] += 1
            report["rows_parsed"] += len(recs)
            report["skipped_major"] += skipped
            parsed.append((name, recs))
            if len(report["samples"]) < 5:
                report["samples"].append({"school": name, "rows": len(recs),
                                          "sample": recs[0] if recs else None})

    if not commit:
        report["dry_run"] = True
        return report

    now = datetime.now(timezone.utc)
    with session_scope() as s:
        for name, recs in parsed:
            for rec in recs:
                canonical, method, _sim = match_university(rec["university_input"])
                if not canonical:
                    continue
                row = s.scalar(select(SchoolLine).where(
                    SchoolLine.year == rec["year"], SchoolLine.province == rec["province"],
                    SchoolLine.subject == rec["subject"], SchoolLine.university == canonical,
                    SchoolLine.group_code == rec["group_code"]))
                if row is None:
                    s.add(SchoolLine(
                        year=rec["year"], province=rec["province"], subject=rec["subject"],
                        batch=rec["batch"], university=canonical,
                        university_input=rec["university_input"][:128],
                        group_code=rec["group_code"], min_score=rec["min_score"],
                        min_rank=rec["min_rank"], data_source="estimated_real",
                        match_method=method, source_url=rec["source_url"],
                        note=rec["note"], operator="import_crawler", updated_at=now))
                    report["inserted"] += 1
                else:
                    changed = (row.min_score != rec["min_score"] or row.min_rank != rec["min_rank"]
                               or row.batch != rec["batch"])
                    if not changed:
                        report["unchanged"] += 1
                        continue
                    s.add(DataChange(dataset="school_lines", year=rec["year"], action="import",
                                    entity=f"{rec['province']}/{rec['subject']}/{canonical}",
                                    field="min_score/min_rank",
                                    old_value=f"{row.min_score}/{row.min_rank}",
                                    new_value=f"{rec['min_score']}/{rec['min_rank']}",
                                    reason="导入掌上高考2025", operator="import_crawler"))
                    row.min_score = rec["min_score"]
                    row.min_rank = rec["min_rank"]
                    row.batch = rec["batch"] or row.batch
                    row.data_source = "estimated_real"
                    row.source_url = rec["source_url"]
                    row.note = rec["note"]
                    row.operator = "import_crawler"
                    report["updated"] += 1
    report["dry_run"] = False

    # 落库完成后再写报告，避免统计为 0 的陈旧快照
    import json as _json
    _json.dump(report, open("/tmp/import_report.json", "w", encoding="utf-8"),
               ensure_ascii=False, default=str)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="导入掌上高考2025 真实院校投档线（对置版式数据侧）")
    ap.add_argument("--commit", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--max-workers", type=int, default=6)
    ap.add_argument("--only", help="仅重试指定院校（逗号分隔），用于补齐瞬断")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    rep = import_all(commit=args.commit, max_workers=args.max_workers, only=only)
    print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
