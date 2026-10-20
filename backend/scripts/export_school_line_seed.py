"""导出院校投档线种子文件（S6）。

用法（在 backend/ 目录下执行）：

    python scripts/export_school_line_seed.py

为什么需要它
------------
院校投档线原先只能靠 ``import_crawler_school_lines.py`` 现拉上游公开爬虫仓库
（1837620622/gaokao-admission-crawler）。那是第三方开源项目，随时可能下架、改名或被
清空——一旦如此，新机器 clone 本仓库后将无法重建任何校线数据。

本脚本把**已入库**的真实数据导出成仓库自带的种子文件并提交入库。之后新环境无需联网，
直接在管理端点「一键落库」即可重建 school_lines，同时也让数据有了可复现的快照基线。

种子一旦入库，后续刷新流程：重新入库（爬虫导入）→ 本脚本导出 → 提交新的种子文件。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:  # 保证中文能正常打印
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from services import school_lines as SL  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="导出院校投档线种子（摆脱对上游爬虫仓库的依赖）")
    ap.add_argument("--path", default=SL.SEED_ESTIMATED,
                    help=f"输出路径（默认 {SL.SEED_ESTIMATED}）")
    ap.add_argument("--data-source", default="estimated_real",
                    help="只导出该来源的行；传空字符串导出全部")
    args = ap.parse_args()

    from db.database import init_db

    init_db(seed=False)

    meta = SL.export_seed(path=args.path, data_source=args.data_source)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    size_kb = round(os.path.getsize(args.path) / 1024, 1)
    print(f"\n已写入 {args.path}（{size_kb} KB）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
