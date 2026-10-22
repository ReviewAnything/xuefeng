"""2026-10 全量回归审计发现的问题的回归测试。

每条用例对应一个已修复的真实缺陷，防止回退：
1. 院校推荐池被仓储层 1000 行上限截断；
2. 普通一本/普通二本共用本科池导致同一院校在两档重复展开；
3. 官方省控线「沿用往年」的真实年份没有透出（2026 版本标「官方」却是 2024 数据）；
4. 等位分换算把参数化样例年当成真实年份；
5. 恰落在锚点上的分数/位次被误标为「区间外外推」；
6. 登录锁定到期后失败计数不清零，一次输错立刻再锁 15 分钟。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import main
from fastapi.testclient import TestClient

from db.database import session_scope
from db.models import AdminUser
from db.seed import hash_password
from services import admin_auth as auth
from services import equiv_score as E
from services import recommend as R
from services import school_lines as SL

c = TestClient(main.app)


# ---------------------------------------------------------------- 院校池完整性

def test_recommend_pool_not_truncated_at_1000():
    """专科池应覆盖全部 1560 所，而不是被 limit=1000 截断。"""
    j = R.recommend_schools("河南", "物理类", 30000, limit=1)
    zk = next(t for t in j["tiers"] if t["tier"] == "专科")
    assert zk["pool_total"] > 1000, f"专科池被截断：{zk['pool_total']}"


def test_recommend_benke_pool_full_size():
    """本科池应是「1308 所本科 − 112 所 211」，而不是恰好 1000 的截断值。"""
    j = R.recommend_schools("河南", "物理类", 30000, limit=1)
    benke = [t for t in j["tiers"] if t["tier"] in ("普通一本", "普通二本")]
    assert benke and all(t["pool_total"] > 1000 for t in benke)


def test_shared_pool_expands_once():
    """一本/二本共用本科池：只能有一档带院校，且两档校名不重叠。"""
    j = R.recommend_schools("广东", "物理类", 40000, limit=50)
    one = next(t for t in j["tiers"] if t["tier"] == "普通一本")
    two = next(t for t in j["tiers"] if t["tier"] == "普通二本")
    names_one = {s["name"] for s in one["schools"]}
    names_two = {s["name"] for s in two["schools"]}
    assert not (names_one & names_two), "同一院校在 一本/二本 两档重复出现"
    assert bool(names_one) != bool(names_two), "两档都不展开或都展开，去重失效"
    assert one["pool_total"] == two["pool_total"]
    shared = one if not names_one else two
    assert shared["pool_shared_with"] == (two if shared is one else one)["tier"]


def test_tier_order_is_batch_order():
    """同档位内按批次顺序（985→211→一本→二本→专科）展示，不按门槛位次打乱。

    跨档位仍按 冲→稳→保→不可及 排（不可及的 985 会排到最后，这是有意的）。
    """
    j = R.recommend_schools("广东", "物理类", 40000, limit=1)
    idx = {"985": 0, "211": 1, "普通一本": 2, "普通二本": 3, "专科": 4}
    runs, cur_level, cur = [], None, []
    for t in j["tiers"]:
        if t["level"] != cur_level:
            if cur:
                runs.append(cur)
            cur_level, cur = t["level"], []
        cur.append(idx[t["tier"]])
    runs.append(cur)
    for run in runs:
        assert run == sorted(run), f"同档位内批次顺序被打乱：{run}"
    assert len(runs) == len({t["level"] for t in j["tiers"]})


# ---------------------------------------------------------------- 官方值年份口径

def test_official_source_year_surfaced():
    """广东 985/211 入门投档线仍是沿用 2024 的官方值，接口必须带上 source_year/carried。

    注：广东 普通一本/二本/专科 现已直接有 2026 官方省控线（source_year=2026, carried=False），
    仍沿用 2024 的只有 985/211 入门投档位次，故断言聚焦这两档，守住「沿用值必须透出」的回归点。
    """
    j = R.recommend_schools("广东", "物理类", 40000, limit=1)
    official = [t for t in j["tiers"] if t["data_source"] == "official"]
    assert official, "广东应有官方省控线覆盖"
    carried = [t for t in official if t["tier"] in ("985", "211")]
    assert carried, "广东应有沿用 2024 的 985/211 入门投档线"
    for t in carried:
        assert t["source_year"] == 2024
        assert t["carried"] is True


def test_api_recommend_exposes_carried_flag():
    r = c.get("/api/recommend/schools", params={
        "province": "广东", "subject": "物理类", "user_rank": 40000, "limit": 1})
    assert r.status_code == 200
    tiers = r.json()["tiers"]
    assert any(t["carried"] and t["source_year"] for t in tiers)


# ---------------------------------------------------------------- 等位分

def test_available_years_excludes_sample():
    years = E.available_years("河南", "物理类")
    assert years and all(y["data_source"] != "sample" for y in years)


def test_exact_anchor_is_not_extrapolated():
    cur = E.curve("河南", "物理类", 2024)
    anchor = cur["anchors"][0]
    score, ext = E.score_of_rank(cur, anchor["rank"])
    assert (score, ext) == (anchor["score"], False)
    rank, ext2 = E.rank_of_score(cur, anchor["score"])
    assert (rank, ext2) == (anchor["rank"], False)


def test_convert_warns_on_mixed_sources():
    out = E.convert("河南", "物理类", 2024, 2026, rank=40000)
    assert out["ok"]
    assert "口径不同" in out["caveat"]


# ---------------------------------------------------------------- 登录锁定
def test_lock_expiry_resets_failed_attempts():
    """锁定期过后应清零计数：否则一次输错立刻重新锁定，正确密码也进不来。"""
    username, pwd = "reg_unlock_probe", "right-pass-2026"
    with session_scope() as s:
        row = s.scalar(select(AdminUser).where(AdminUser.username == username))
        if row is None:
            h, salt = hash_password(pwd)
            s.add(AdminUser(username=username, password_hash=h, salt=salt,
                            role="admin", must_change_password=False))
    for _ in range(auth.LOGIN_MAX_FAILS):
        auth.login(username, "wrong-pass", ip="10.0.0.1")
    with session_scope() as s:
        row = s.scalar(select(AdminUser).where(AdminUser.username == username))
        assert row.failed_attempts >= auth.LOGIN_MAX_FAILS
        row.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)

    first = auth.login(username, "wrong-pass", ip="10.0.0.1")
    assert first["reason"] == "bad_credentials", "锁定期已过，单次输错不应立即重新锁定"
    ok = auth.login(username, pwd, ip="10.0.0.1")
    assert ok["ok"], "计数清零后，正确密码应能登录"


# ---------------------------------------------------------------- 校线导入

def _import_csv(text: str, filename: str, mode: str) -> dict:
    return SL.import_table(
        text.encode("utf-8"), filename,
        {"province": "西藏", "subject": "物理类", "source_url": "https://example.edu.cn/xz"},
        dry_run=False, operator="regression", mode=mode)


def _cleanup_xz_official():
    """清理本文件校线测试写入的「西藏官方」行，避免污染共享测试库（影响 health 断言）。"""
    from db.models import DataChange, SchoolLine
    from sqlalchemy import delete

    with session_scope() as s:
        s.execute(delete(SchoolLine).where(
            SchoolLine.province == "西藏", SchoolLine.data_source == "official"))
        s.execute(delete(DataChange).where(DataChange.dataset == "school_lines"))
    SL.invalidate_cache()


def test_cli_schema_helper_creates_tables():
    """CLI 在全新库上也要能跑（建表幂等），否则 --coverage/--commit 直接崩。"""
    from scripts.import_school_lines import _ensure_schema
    _ensure_schema()
    assert SL.coverage()["total"] >= 0


def test_replace_mode_keeps_are_scoped_per_year():
    """replace 的 keep 集合必须按 (年,省,科类) 分开。

    文件同时含 2023/2024 两个 scope 时，旧实现用全局 keep，
    会让「2024 已不存在、但 2023 仍有」的院校在 2024 漏删。
    """
    _import_csv(
        "年份,院校名称,最低分,最低位次,专业组\n"
        "2024,西藏大学,500,10000,01\n"
        "2023,西藏大学,490,11000,01\n"
        "2024,西藏藏医药大学,450,20000,01\n",
        "seed.csv", "merge")

    _import_csv(
        "年份,院校名称,最低分,最低位次,专业组\n"
        "2023,西藏大学,490,11000,01\n"
        "2024,西藏藏医药大学,450,20000,01\n",
        "replace.csv", "replace")

    rows_2024 = SL.lines_for("西藏", "物理类", year=2024)["rows"]
    names_2024 = {r["university"] for r in rows_2024}
    assert "西藏藏医药大学" in names_2024
    assert "西藏大学" not in names_2024, "2024 年的旧行没有被 replace 删除"

    names_2023 = {r["university"] for r in SL.lines_for("西藏", "物理类", year=2023)["rows"]}
    assert "西藏大学" in names_2023, "2023 年（文件内同样存在的 scope）不应被误删"
    _cleanup_xz_official()
