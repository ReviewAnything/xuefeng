"""省考试院官方原表 → official 校线（S8-A + P1 批量）。

单文件用法（来源链接必填——没有可点开的官方链接就不配叫 official）：

    cd backend
    python scripts/import_official_table.py 广东_2024_物理类.csv \\
        --province 广东 --year 2024 --subject 物理类 --batch 本科批 \\
        --source-url https://eea.gd.gov.cn/... --dry-run     # 只预览，不写库
    python scripts/import_official_table.py 广东_2024_物理类.csv ... --commit

批量投喂（P1：扫描整个目录，逐文件落库）：

    python scripts/import_official_table.py --landing-dir backend/data/official --dry-run
    python scripts/import_official_table.py --landing-dir backend/data/official --commit \\
        --province 广东 --year 2024 --subject 物理类 --source-url https://...   # 文件级默认值

批量模式下每个文件可用自带 meta（JSON 的 ``meta`` 块）覆盖命令行默认值；
没有 meta 的 CSV/XLSX 用命令行参数（省 / 年 / 科类 / 来源链接）兜底，
什么都不带且解析不出 source_url 的文件会被跳过并写明原因。

表格要求：CSV / XLSX / JSON，至少含「院校名称」+「最低分」或「最低位次」列
（列名支持常见别名，见 services/school_lines.py 的 HEADER_ALIASES）。

落库成功后会往 backend/data/official/sources.json 写一条溯源台账
（文件名 / sha256 / 省 / 年 / 科类 / 来源链接 / 行数 / 存档路径），供审计与 health 上报；
原表字节同时按 sha256 留档进 backend/data/official/archive/（P2）。
``--copy-to-landing`` 会把原表复制进落地区，后续可直接用「一键落库」重放。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import school_lines as SL  # noqa: E402

SKIP_FILES = {"sources.json", "acquisition_ledger.json", "README.md"}


def _print_report(report: dict) -> None:
    mode = "预览（未写库）" if report.get("dry_run") else "落库完成"
    print(f"== {mode} ==  文件 {report.get('file')}  格式 {report.get('format', '')}")
    print(f"解析 {report.get('parsed', 0)} 行 → 可落库 {report.get('accepted', 0)} 行，"
          f"拒收 {report.get('rejected', 0)} 行")
    if not report.get("dry_run"):
        print(f"新增 {report.get('inserted', 0)} / 更新 {report.get('updated', 0)} / "
              f"未变 {report.get('unchanged', 0)}")
    if report.get("provenance_warnings"):
        print(f"注意：{report['provenance_warnings']} 行的来源域名不像考试院机构，已留痕待人工复核")
    cross = report.get("cross_check") or {}
    if cross.get("warnings"):
        print(f"注意：{cross['warnings']} 行位次与当年一分一段表偏差超 {cross.get('threshold_pct', 25)}%，"
              f"已写进备注待人工复核")
    for item in (report.get("rejected_samples") or [])[:10]:
        print(f"  拒收：{item}")
    if report.get("registry", {}).get("ok"):
        e = report["registry"]["entry"]
        archive = f" | 存档 {e['archive']}" if e.get("archive") else ""
        print(f"溯源已登记：{e['file']} | {e['province']} {e['year']} {e['subject']} | "
              f"{e['rows']} 行 | sha256 {e['sha256'][:16]}…{archive}")
    elif report.get("registry", {}).get("error"):
        print(f"溯源登记失败：{report['registry']['error']}", file=sys.stderr)


def run_single(args) -> int:
    path = args.file
    if not os.path.exists(path):
        print(f"文件不存在：{path}", file=sys.stderr)
        return 2
    if not args.source_url:
        print("--source-url 必填：official 行必须能追到可点开的官方来源", file=sys.stderr)
        return 2

    with open(path, "rb") as f:
        raw = f.read()
    defaults = _cli_defaults(args)

    report = SL.import_official_table(raw, os.path.basename(path), defaults,
                                      dry_run=not args.commit, operator="cli",
                                      register=args.commit)
    if not report.get("ok"):
        print(f"解析失败：{report.get('error')}", file=sys.stderr)
        if report.get("detected_headers"):
            print(f"识别到的表头：{report['detected_headers']}", file=sys.stderr)
        return 1

    if args.copy_to_landing and args.commit:
        os.makedirs(SL.OFFICIAL_DIR, exist_ok=True)
        dst = os.path.join(SL.OFFICIAL_DIR, os.path.basename(path))
        if os.path.abspath(dst) != os.path.abspath(path):
            shutil.copyfile(path, dst)
            print(f"已复制到落地区：{dst}")

    _print_report(report)
    return 0


def _cli_defaults(args) -> dict:
    return {k: v for k, v in {
        "province": args.province, "year": args.year, "subject": args.subject,
        "batch": args.batch, "source_url": args.source_url, "source_org": args.source_org,
    }.items() if v not in (None, "")}


def _landing_files(directory: str) -> list[str]:
    out = []
    for name in sorted(os.listdir(directory)):
        low = name.lower()
        if name.startswith(".") or name in SKIP_FILES or low.endswith(".meta.json"):
            continue
        if low.endswith((".json", ".csv", ".xlsx", ".xlsm")):
            out.append(os.path.join(directory, name))
    return out


def run_landing(args) -> int:
    """批量投喂：扫描目录逐文件落库，汇总报告。"""
    directory = args.landing_dir
    if not os.path.isdir(directory):
        print(f"目录不存在：{directory}", file=sys.stderr)
        return 2
    files = _landing_files(directory)
    if not files:
        print(f"目录里没有可投喂的原表（支持 .csv/.xlsx/.json）：{directory}", file=sys.stderr)
        return 1
    print(f"扫描 {directory}：{len(files)} 个文件（commit={'是' if args.commit else '否，仅预览'}）")
    totals = {"files": 0, "ok_files": 0, "parsed": 0, "accepted": 0, "rejected": 0,
              "inserted": 0, "updated": 0, "cross_warnings": 0}
    failures: list[str] = []
    for path in files:
        name = os.path.basename(path)
        totals["files"] += 1
        with open(path, "rb") as f:
            raw = f.read()
        defaults = _cli_defaults(args)
        # JSON 自带 meta 时优先（文件级 > 命令行）
        if path.lower().endswith(".json"):
            try:
                doc = json.loads(raw.decode("utf-8"))
                meta = doc.get("meta") if isinstance(doc, dict) else None
                if isinstance(meta, dict):
                    defaults.update({k: v for k, v in meta.items()
                                     if k in ("year", "province", "subject", "batch",
                                              "source_url", "source_org") and v})
            except (UnicodeDecodeError, ValueError):
                pass
        if not defaults.get("source_url"):
            failures.append(f"{name}：缺来源链接（JSON 请写 meta.source_url，"
                            f"或用 --source-url 统一指定）")
            continue
        try:
            report = SL.import_official_table(raw, name, defaults,
                                              dry_run=not args.commit, operator="cli",
                                              register=args.commit)
        except Exception as exc:  # noqa: BLE001 - 单文件失败不中断整批
            failures.append(f"{name}：{type(exc).__name__}: {exc}")
            continue
        if not report.get("ok"):
            failures.append(f"{name}：{report.get('error', '解析失败')}")
            continue
        totals["ok_files"] += 1
        for key in ("parsed", "accepted", "rejected", "inserted", "updated"):
            totals[key] += int(report.get(key) or 0)
        totals["cross_warnings"] += int((report.get("cross_check") or {}).get("warnings") or 0)
        _print_report(report)

    print("\n== 批量汇总 ==")
    print(f"文件 {totals['files']} 个（成功 {totals['ok_files']}）| "
          f"解析 {totals['parsed']} 行 | 可落库 {totals['accepted']} / 拒收 {totals['rejected']}")
    if not args.commit:
        print("预览模式未写库；确认后加 --commit 重新执行")
    else:
        print(f"新增 {totals['inserted']} / 更新 {totals['updated']} | "
              f"位次交叉校验告警 {totals['cross_warnings']} 行")
    if failures:
        print(f"\n跳过/失败 {len(failures)} 个：")
        for item in failures:
            print(f"  - {item}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="官方原表落库（S8-A + P1 批量）")
    ap.add_argument("file", nargs="?", help="CSV / XLSX / JSON 原表路径（与 --landing-dir 二选一）")
    ap.add_argument("--landing-dir", default="", help="批量模式：扫描该目录逐文件投喂")
    ap.add_argument("--province", default="", help="省份（表内无该列时必填）")
    ap.add_argument("--year", type=int, default=None, help="年份")
    ap.add_argument("--subject", default="", help="科类：物理类 / 历史类 / 综合")
    ap.add_argument("--batch", default="", help="批次，如 本科批")
    ap.add_argument("--source-url", default="", help="省考试院原表地址（必填）")
    ap.add_argument("--source-org", default="", help="发布机构，如 广东省教育考试院")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写库")
    ap.add_argument("--commit", action="store_true", help="真正写库")
    ap.add_argument("--copy-to-landing", action="store_true",
                    help="把原表复制进 backend/data/official/，便于重放")
    args = ap.parse_args()

    if args.landing_dir:
        return run_landing(args)
    if args.file:
        return run_single(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
