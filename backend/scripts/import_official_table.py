"""省考试院官方原表 → official 校线（S8-A）。

用法（来源链接必填——没有可点开的官方链接就不配叫 official）：

    cd backend
    python scripts/import_official_table.py 广东_2024_物理类.csv \\
        --province 广东 --year 2024 --subject 物理类 --batch 本科批 \\
        --source-url https://eea.gd.gov.cn/... --dry-run     # 只预览，不写库
    python scripts/import_official_table.py 广东_2024_物理类.csv ... --commit

表格要求：CSV / XLSX / JSON，至少含「院校名称」+「最低分」或「最低位次」列
（列名支持常见别名，见 services/school_lines.py 的 HEADER_ALIASES）。
年份 / 省份 / 科类 / 批次 / 来源链接 既可写在表里，也可用命令行参数统一指定。

落库成功后会往 backend/data/official/sources.json 写一条溯源台账
（文件名 / sha256 / 省 / 年 / 科类 / 来源链接 / 行数），供审计与 health 上报。

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


def main() -> int:
    ap = argparse.ArgumentParser(description="官方原表落库（S8-A）")
    ap.add_argument("file", help="CSV / XLSX / JSON 原表路径")
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

    path = args.file
    if not os.path.exists(path):
        print(f"文件不存在：{path}", file=sys.stderr)
        return 2
    if not args.source_url:
        print("--source-url 必填：official 行必须能追到可点开的官方来源", file=sys.stderr)
        return 2

    with open(path, "rb") as f:
        raw = f.read()
    defaults = {k: v for k, v in {
        "province": args.province, "year": args.year, "subject": args.subject,
        "batch": args.batch, "source_url": args.source_url, "source_org": args.source_org,
    }.items() if v not in (None, "")}

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

    mode = "预览（未写库）" if report.get("dry_run") else "落库完成"
    print(f"== {mode} ==  文件 {report.get('file')}  格式 {report.get('format', '')}")
    print(f"解析 {report.get('parsed', 0)} 行 → 可落库 {report.get('accepted', 0)} 行，"
          f"拒收 {report.get('rejected', 0)} 行")
    if not report.get("dry_run"):
        print(f"新增 {report.get('inserted', 0)} / 更新 {report.get('updated', 0)} / "
              f"未变 {report.get('unchanged', 0)}")
    if report.get("provenance_warnings"):
        print(f"注意：{report['provenance_warnings']} 行的来源域名不像考试院机构，已留痕待人工复核")
    for item in (report.get("rejected_samples") or [])[:10]:
        print(f"  拒收：{item}")
    if report.get("registry", {}).get("ok"):
        e = report["registry"]["entry"]
        print(f"溯源已登记：{e['file']} | {e['province']} {e['year']} {e['subject']} | "
              f"{e['rows']} 行 | sha256 {e['sha256'][:16]}…")
    elif report.get("registry", {}).get("error"):
        print(f"溯源登记失败：{report['registry']['error']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
