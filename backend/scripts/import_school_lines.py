"""院校投档线导入命令行（D1）。

用法（在 backend/ 目录下执行）：

    # 1) 先 dry-run 看匹配报告（默认就是 dry-run，不写库）
    python scripts/import_school_lines.py --file ../data/henan_2024_physics.csv \
        --year 2024 --province 河南 --subject 物理类

    # 2) 确认无误后落库
    python scripts/import_school_lines.py --file ... --year 2024 --province 河南 \
        --subject 物理类 --commit --source-url https://www.haeea.cn/...

    # 3) 整省替换（删除文件里没有的旧行）
    python scripts/import_school_lines.py --file ... --commit --mode replace

    # 4) 查看导入覆盖概况
    python scripts/import_school_lines.py --coverage

表格要求：至少含「院校名称」+「最低分」或「最低位次」两列；
其余列（专业组/批次/科类/省份/年份/来源）可选，缺省用命令行参数补齐。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import school_lines as SL  # noqa: E402


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description="导入院校投档线（CSV/XLSX → school_lines）")
    ap.add_argument("--file", help="CSV / XLSX 路径")
    ap.add_argument("--year", type=int, help="缺省年份（表格无「年份」列时使用）")
    ap.add_argument("--province", help="缺省省份（表格无「省份」列时使用）")
    ap.add_argument("--subject", help="缺省科类：物理类 / 历史类 / 综合")
    ap.add_argument("--source-url", default="", help="数据出处链接（给了才标记 official）")
    ap.add_argument("--operator", default="cli", help="操作人（写入审计）")
    ap.add_argument("--mode", choices=["merge", "replace"], default="merge",
                    help="merge=只增改（默认）；replace=同时删除该范围文件外的旧行")
    ap.add_argument("--commit", action="store_true", help="真正写库（默认只 dry-run）")
    ap.add_argument("--coverage", action="store_true", help="只看导入覆盖概况")
    ap.add_argument("--json", action="store_true", help="单行 JSON 输出（便于 CI 消费）")
    args = ap.parse_args()

    if args.coverage:
        data = SL.coverage()
        print(json.dumps(data, ensure_ascii=False) if args.json else json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if not args.file:
        ap.error("需要 --file（或使用 --coverage 查看概况）")
    if not os.path.exists(args.file):
        ap.error(f"文件不存在：{args.file}")

    with open(args.file, "rb") as f:
        raw = f.read()

    defaults = {"year": args.year, "province": args.province, "subject": args.subject,
                "source_url": args.source_url, "data_source": "official" if args.source_url else ""}
    report = SL.import_table(raw, os.path.basename(args.file), defaults,
                             dry_run=not args.commit, operator=args.operator, mode=args.mode)

    if not report.get("ok"):
        _print(report)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        _print(report)
    if report.get("dry_run"):
        print("\n（dry-run：未写库。确认后加 --commit 落库）", file=sys.stderr)
    if report.get("invalid_count") or report.get("unmatched_count"):
        print(f"\n注意：{report['invalid_count']} 行校验未过、{report['unmatched_count']} 行校名未匹配，"
              "详见 invalid / unmatched 清单。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
