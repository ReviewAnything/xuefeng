"""共享测试夹具：保证测试套件在全新库上自封闭。

历史问题（2026-10-21 全新库复现）：school_lines 种子不在 init_db/sync_all 的
TARGETS 里，全新库要等到 test_school_line_seed（字母序靠后）才被写入 14020 行
estimated_real；此前全量测试「全绿」依赖共享库的历史存量，全新库上
alignment_evidence / api / official_table 家族会假红（gate_profile combos==0、
覆盖率 total==official 等）。

解决：会话开始时统一幂等预播种 estimated 种子（import_seed 本身幂等，
重复跑 inserted=0），任何库状态都成立。official 行仍须各用例显式落库/清理，
维持「默认库无官方行」的设计事实。
"""
import os

# 与各测试文件的 setdefault 保持一致：无显式环境时用统一测试库
os.environ.setdefault("XUEFENG_DB_PATH", "/tmp/xf_test.db")

import pytest


@pytest.fixture(scope="session", autouse=True)
def seed_school_lines_once():
    """预播种校线（estimated_real 14020 行），幂等。

    先 init_db 建表再 import_seed——import_seed 本身不建表，
    只跑单文件（如 test_rank_tables）时不能依赖套件里其它测试先行建表。
    """
    from db.database import init_db
    from services import school_lines as SL

    init_db(seed=True)
    report = SL.import_seed(commit=True, include=["estimated"])
    assert "error" not in report, report
    yield
