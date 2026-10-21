"""近五年官方省控线（年度罗盘）测试：数据完整性 + 按年查询 API + 落库脚本。

数据文件：backend/data/admission_control_lines_2022_2026.json
落库脚本：scripts/import_control_lines.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DATA_FILE = os.path.join(_BACKEND, "data", "admission_control_lines_2022_2026.json")

# 优先沿用 pytest 运行时的测试库；否则用一个独立文件，避免误写生产库
_TEST_DB = os.environ.get("XUEFENG_DB_PATH", "/tmp/xf_test_cl.db")
os.environ.setdefault("XUEFENG_DB_PATH", _TEST_DB)

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402  (触发启动播种，写到 _TEST_DB)

client = TestClient(main.app)


# --------------------------------------------------------------------------
# 1. 数据完整性
# --------------------------------------------------------------------------
def test_json_integrity():
    d = json.load(open(_DATA_FILE, encoding="utf-8"))
    meta = d["meta"]
    assert meta["years"] == [2022, 2023, 2024, 2025, 2026]
    assert meta["coverage_count"] == 31
    assert len(meta["coverage"]) == 31
    assert meta["rank_included"] is False
    for y in meta["years"]:
        blk = d["by_year"][str(y)]
        assert set(blk["batch_lines"]) == set(meta["coverage"])
        for p, subs in blk["batch_lines"].items():
            for s, tiers in subs.items():
                assert s in ("物理类", "历史类"), f"{y} {p} 科类异常: {s}"
                for t, o in tiers.items():
                    assert t in ("普通一本", "普通二本", "专科"), f"{y} {p} 档位异常: {t}"
                    assert isinstance(o["score"], int) and o["score"] > 0
        # 每年必须有可追溯来源链接
        assert meta["sources"][str(y)].startswith("https://"), f"{y} 缺 source_url"


def test_json_sample_values():
    d = json.load(open(_DATA_FILE, encoding="utf-8"))
    # 河南 2024 文理分科
    henan24 = d["by_year"]["2024"]["batch_lines"]["河南"]
    assert henan24["物理类"]["普通一本"]["score"] == 511
    assert henan24["历史类"]["普通一本"]["score"] == 521
    # 浙江 2025 一段/二段
    zhejiang25 = d["by_year"]["2025"]["batch_lines"]["浙江"]
    assert zhejiang25["物理类"]["普通二本"]["score"] == 490
    assert zhejiang25["物理类"]["专科"]["score"] == 268
    # 北京 2026 综合双写
    bj26 = d["by_year"]["2026"]["batch_lines"]["北京"]
    assert bj26["物理类"]["普通一本"]["score"] == bj26["历史类"]["普通一本"]["score"] == 521
    # 防回归：官方主表「历史列|物理列」两列并列，绝不能把历史列当综合双写。
    # 河北 2025：历史特招 527 / 物理特招 499（曾因两列混写全写成 527）
    hb25 = d["by_year"]["2025"]["batch_lines"]["河北"]
    assert hb25["历史类"]["普通一本"]["score"] == 527
    assert hb25["物理类"]["普通一本"]["score"] == 499
    assert hb25["物理类"]["普通二本"]["score"] == 459
    # 河南 2025：历史特招 552 / 物理特招 535
    hn25 = d["by_year"]["2025"]["batch_lines"]["河南"]
    assert hn25["历史类"]["普通一本"]["score"] == 552
    assert hn25["物理类"]["普通一本"]["score"] == 535
    # 吉林/黑龙江 2024 已改新高考，不再是 2023 的文理值
    jl24 = d["by_year"]["2024"]["batch_lines"]["吉林"]
    assert jl24["历史类"]["普通二本"]["score"] == 369
    assert jl24["物理类"]["普通二本"]["score"] == 345


# --------------------------------------------------------------------------
# 2. 按年查询 API
# --------------------------------------------------------------------------
def test_api_years():
    r = client.get("/api/admission/control-line-years")
    assert r.status_code == 200
    j = r.json()
    assert j["years"] == [2022, 2023, 2024, 2025, 2026]
    assert j["coverage_count"] == 31
    assert j["rank_included"] is False
    assert all(y["province_count"] == 31 for y in j["by_year"].values())


def test_api_lines_by_year_and_province():
    r = client.get("/api/admission/control-lines?year=2025&province=河南")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["year"] == 2025
    assert "河南" in j["data"]
    # 河南 2025 首年新高考，历史/物理两列分列：历史特招 552，物理特招 535
    assert j["data"]["河南"]["历史类"]["普通一本"]["score"] == 552
    assert j["data"]["河南"]["物理类"]["普通一本"]["score"] == 535
    assert j["data"]["河南"]["物理类"]["普通二本"]["score"] == 427
    assert j["source_url"].startswith("https://")


def test_api_lines_all_provinces_year():
    r = client.get("/api/admission/control-lines?year=2026")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["provinces_seen"] == 31


def test_api_lines_invalid_year():
    r = client.get("/api/admission/control-lines?year=2099")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert "2099" in j["error"]


# --------------------------------------------------------------------------
# 3. 落库脚本：insert-only + 跳过生效年份（不扰动实时排名）
# --------------------------------------------------------------------------
# 沙箱下 pytest 的 tmp_path fixture 会报 PermissionError（拦截 /private/tmp/pytest-of-*），
# 改用项目内 .bk_tmp 临时目录（与 test_observability._mk_tmp_dir 同思路）。
_BK_TMP = os.path.join(_BACKEND, "tests", ".bk_tmp")


@pytest.fixture()
def tmp_db_dir():
    os.makedirs(_BK_TMP, exist_ok=True)
    d = tempfile.mkdtemp(prefix="cl_", dir=_BK_TMP)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_import_insert_only_and_skips_active(tmp_db_dir):
    db = os.path.join(tmp_db_dir, "cl_import.db")
    env = dict(os.environ)
    env["XUEFENG_DB_PATH"] = str(db)
    py = sys.executable

    # 先播种（拿到生效年份的估算/官方基线）
    seed = subprocess.run(
        [py, "-c", "from db.database import init_db; init_db(seed=True)"],
        env=env, cwd=_BACKEND, capture_output=True, text=True,
    )
    assert seed.returncode == 0, seed.stderr

    # dry-run 不应写库
    dry = subprocess.run(
        [py, "scripts/import_control_lines.py", "--dry-run"],
        env=env, cwd=_BACKEND, capture_output=True, text=True,
    )
    assert dry.returncode == 0, dry.stderr
    assert "dry-run" in dry.stdout

    # 真实导入
    real = subprocess.run(
        [py, "scripts/import_control_lines.py"],
        env=env, cwd=_BACKEND, capture_output=True, text=True,
    )
    assert real.returncode == 0, real.stderr

    # 断言：2022–2025 应有 official 落库；2026（生效年份）被跳过
    checker = os.path.join(tmp_db_dir, "check_counts.py")
    with open(checker, "w", encoding="utf-8") as f:
        f.write(
            "import sys\n"
            f"sys.path.insert(0, {_BACKEND!r})\n"
            "from db.database import session_scope\n"
            "from db.models import AdmissionBaseline\n"
            "from sqlalchemy import select, func\n"
            "with session_scope() as s:\n"
            "    off = s.scalar(select(func.count()).select_from(AdmissionBaseline)\n"
            "        .where(AdmissionBaseline.data_source == 'official', AdmissionBaseline.year < 2026))\n"
            "    est_2026 = s.scalar(select(func.count()).select_from(AdmissionBaseline)\n"
            "        .where(AdmissionBaseline.year == 2026, AdmissionBaseline.data_source == 'estimated'))\n"
            "print(off, est_2026)\n"
        )
    count = subprocess.run(
        [py, checker],
        env=env, cwd=_BACKEND, capture_output=True, text=True,
    )
    assert count.returncode == 0, count.stderr
    off_rows, est_2026 = map(int, count.stdout.strip().split())
    assert off_rows > 0, "2022–2025 应写入官方省控线"
    assert est_2026 > 0, "生效年份(2026)的估算基线不应被覆盖"


def test_import_idempotent(tmp_db_dir):
    db = os.path.join(tmp_db_dir, "cl_idem.db")
    env = dict(os.environ)
    env["XUEFENG_DB_PATH"] = str(db)
    py = sys.executable
    subprocess.run([py, "-c", "from db.database import init_db; init_db(seed=True)"],
                   env=env, cwd=_BACKEND, capture_output=True, text=True, check=True)
    subprocess.run([py, "scripts/import_control_lines.py"],
                   env=env, cwd=_BACKEND, capture_output=True, text=True, check=True)
    r2 = subprocess.run([py, "scripts/import_control_lines.py"],
                        env=env, cwd=_BACKEND, capture_output=True, text=True, check=True)
    # 第二次跑应为 0 新增（幂等）
    assert "新增 0 行" in r2.stdout, r2.stdout


def test_sync_admission_upgrades_to_31_province_official():
    """seed 现在把 31 省官方省控线接入 admission_baselines（含合并批次省的 综合 科目别名），
    且官方行保留 estimated 的 min_rank（不置 0，避免拉垮冲稳保实时排名）。"""
    import os as _os
    _bk = os.path.join(_BACKEND, ".bk_tmp")
    db = os.path.join(_bk, f"prov_{os.getpid()}.db")
    env = dict(_os.environ, XUEFENG_DB_PATH=db)
    py = sys.executable
    r = subprocess.run([py, "-c", "from db.database import init_db; init_db(seed=True)"],
                       env=env, cwd=_BACKEND, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    checker = os.path.join(_bk, f"chk_{os.getpid()}.py")
    with open(checker, "w", encoding="utf-8") as f:
        f.write(
            "import sys\n"
            f"sys.path.insert(0, {_BACKEND!r})\n"
            "from db.database import session_scope\n"
            "from db.models import AdmissionBaseline\n"
            "from sqlalchemy import select\n"
            "from db import repository as repo\n"
            "cov = repo.official_coverage()\n"
            "with session_scope() as s:\n"
            "    rows = s.scalars(select(AdmissionBaseline)).all()\n"
            "    ctrl_off = {r.province for r in rows if r.data_source=='official' and r.tier in ('普通一本','普通二本','专科')}\n"
            "    sh = [r for r in rows if r.province=='上海' and r.subject=='综合' and r.tier=='普通一本']\n"
            "    print(len(cov), len(ctrl_off), (sh[0].min_rank if sh else -1))\n"
        )
    out = subprocess.run([py, checker], env=env, cwd=_BACKEND, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    n_cov, n_ctrl, sh_rank = (int(x) for x in out.stdout.strip().split())
    assert n_cov == 31, cov  # 覆盖率 31 省
    assert n_ctrl == 31
    assert sh_rank > 0, "官方省控线行的 min_rank 不应为 0"
