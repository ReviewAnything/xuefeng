"""数据管理命令行：年度更新、单年补丁、校验、发布与回滚。

用法（在 backend/ 目录下执行）：

    python scripts/manage_data.py status
    python scripts/manage_data.py new-year  --from 2026 --to 2027
    python scripts/manage_data.py validate  2027
    python scripts/manage_data.py patch     --province 河南 --subject 物理类 --tier 一本 \
                                            --year 2027 --min-rank 130000 --min-score 540 \
                                            --source-url https://... --operator alice
    python scripts/manage_data.py publish   2027
    python scripts/manage_data.py rollback  2026
    python scripts/manage_data.py pending   2027
    python scripts/manage_data.py changes   --limit 20
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import repository as repo            # noqa: E402
from services import data_versions as DV     # noqa: E402


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_status(args) -> None:
    _print(DV.status(args.dataset))


def cmd_new_year(args) -> None:
    _print(DV.clone_year(args.from_year, args.to_year, dataset=args.dataset,
                         operator=args.operator, note=args.note or ""))


def cmd_validate(args) -> None:
    result = DV.validate_year(args.year, args.dataset)
    _print(result)
    sys.exit(0 if result["ok"] else 1)


def cmd_publish(args) -> None:
    result = DV.publish_year(args.year, dataset=args.dataset, operator=args.operator,
                             force=args.force)
    _print(result)
    sys.exit(0 if result.get("ok") else 1)


def cmd_rollback(args) -> None:
    result = DV.rollback(args.dataset, args.year, operator=args.operator, reason=args.reason or "")
    _print(result)
    sys.exit(0 if result.get("ok") else 1)


def cmd_pending(args) -> None:
    _print(DV.pending_updates(args.year, args.dataset))


def cmd_changes(args) -> None:
    _print(DV.changes(args.dataset, args.year, args.limit))


def cmd_patch(args) -> None:
    """按 (年份/省/科类/批次) 定位并修改一条基线。"""
    rows = repo.baseline_rows(province=args.province, subject=args.subject, year=args.year)
    row = next((r for r in rows if r["tier"] == args.tier), None)
    if row is None:
        print(json.dumps({"ok": False, "error": f"未找到 {args.year}/{args.province}/"
                                                f"{args.subject}/{args.tier}"}, ensure_ascii=False))
        sys.exit(1)
    payload = {
        "min_score": args.min_score, "min_rank": args.min_rank,
        "data_source": args.data_source, "source_url": args.source_url,
        "line": args.line, "source_year": args.source_year,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    if not payload:
        print(json.dumps({"ok": False, "error": "没有提供任何待修改字段"}, ensure_ascii=False))
        sys.exit(1)
    result = DV.patch_baseline(row["id"], payload, operator=args.operator, reason=args.reason or "",
                               publish=False)
    _print(result)
    sys.exit(0 if result.get("ok") else 1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="雪峰 · 后端数据管理")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="版本总览")
    s.add_argument("--dataset", default="admission")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("new-year", help="以某年为蓝本创建新年度草稿")
    s.add_argument("--from", dest="from_year", type=int, required=True)
    s.add_argument("--to", dest="to_year", type=int, required=True)
    s.add_argument("--dataset", default="admission")
    s.add_argument("--note", default="")
    s.add_argument("--operator", default="cli")
    s.set_defaults(func=cmd_new_year)

    s = sub.add_parser("validate", help="发布前校验")
    s.add_argument("year", type=int)
    s.add_argument("--dataset", default="admission")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("publish", help="发布为生效版本")
    s.add_argument("year", type=int)
    s.add_argument("--dataset", default="admission")
    s.add_argument("--force", action="store_true")
    s.add_argument("--operator", default="cli")
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("rollback", help="回滚到指定年份")
    s.add_argument("year", type=int)
    s.add_argument("--dataset", default="admission")
    s.add_argument("--reason", default="")
    s.add_argument("--operator", default="cli")
    s.set_defaults(func=cmd_rollback)

    s = sub.add_parser("pending", help="待更新清单")
    s.add_argument("year", type=int, nargs="?")
    s.add_argument("--dataset", default="admission")
    s.set_defaults(func=cmd_pending)

    s = sub.add_parser("changes", help="变更审计")
    s.add_argument("--dataset", default=None)
    s.add_argument("--year", type=int, default=None)
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_changes)

    s = sub.add_parser("patch", help="修改单条基线")
    s.add_argument("--year", type=int, required=True)
    s.add_argument("--province", required=True)
    s.add_argument("--subject", required=True)
    s.add_argument("--tier", required=True)
    s.add_argument("--min-score", type=int, default=None)
    s.add_argument("--min-rank", type=int, default=None)
    s.add_argument("--data-source", default=None)
    s.add_argument("--source-url", default=None)
    s.add_argument("--source-year", type=int, default=None)
    s.add_argument("--line", default=None)
    s.add_argument("--reason", default="")
    s.add_argument("--operator", default="cli")
    s.set_defaults(func=cmd_patch)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
