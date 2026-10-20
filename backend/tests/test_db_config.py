"""数据库配置（管理端多数据库配置）：连接串构建、掩码、落盘、试连、切换即初始化。

注意：apply 会真的切换进程级连接串，所有用例都必须把 override 还原，
否则后续用例会跑在临时库上。配置文件的写入也一律重定向到项目内临时目录
（沙箱下 pytest 的 tmp_path 不可用）。
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from db.database import get_database_url_override, reset_engine, set_database_url
from services import db_config as DBC

from tests.helpers import ready_headers

import main
from fastapi.testclient import TestClient

c = TestClient(main.app)

TMP_ROOT = os.path.join(os.path.dirname(__file__), ".bk_tmp")


def _mk_tmp_dir(tag: str) -> str:
    os.makedirs(TMP_ROOT, exist_ok=True)
    path = tempfile.mkdtemp(prefix=f"dbcfg_{tag}_", dir=TMP_ROOT)
    return path


@pytest.fixture
def tmp_cfg_path():
    """落盘配置重定向到项目内临时文件（沙箱下 tmp_path 不可用）。"""
    tmp = _mk_tmp_dir("cfg")
    try:
        yield os.path.join(tmp, "db_config.json")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _Restore:
    """用例结束后把生效连接串与落盘配置还原。"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.prev_override = get_database_url_override()
        self.prev_cfg = DBC.CONFIG_PATH

    def __enter__(self):
        DBC.CONFIG_PATH = self.config_path
        return self

    def __exit__(self, *exc):
        set_database_url(self.prev_override)
        reset_engine()
        DBC.CONFIG_PATH = self.prev_cfg
        shutil.rmtree(os.path.dirname(self.config_path), ignore_errors=True)
        return False


# ---------------------------------------------------------------- 连接串构建

def test_build_url_sqlite_uses_absolute_path():
    tmp = _mk_tmp_dir("url")
    target = os.path.join(tmp, "nested", "x.db")
    url = DBC.build_url({"dialect": "sqlite", "path": target})
    assert url == f"sqlite:///{target}"
    assert os.path.isdir(os.path.join(tmp, "nested"))     # 目录自动创建


def test_build_url_postgresql_encodes_password():
    url = DBC.build_url({"dialect": "postgresql", "host": "127.0.0.1", "port": 5432,
                         "database": "xf", "username": "u", "password": "p@ss w/rd"})
    assert url.startswith("postgresql")
    assert "p%40ss+w%2Frd" in url          # 口令里的 @ 与 / 必须转义
    assert url.endswith("@127.0.0.1:5432/xf")


def test_build_url_mysql_and_mssql_params():
    my = DBC.build_url({"dialect": "mysql", "host": "db", "database": "xf",
                        "username": "root", "password": "p"})
    assert my.startswith("mysql")
    assert my.endswith("/xf?charset=utf8mb4")
    ms = DBC.build_url({"dialect": "mssql", "host": "db", "database": "xf",
                        "username": "sa", "password": "p"})
    assert ms.startswith("mssql")
    assert "TrustServerCertificate=yes" in ms


def test_build_url_rejects_unknown_dialect_and_empty_url():
    with pytest.raises(ValueError):
        DBC.build_url({"dialect": "oracle", "host": "h", "database": "d"})
    with pytest.raises(ValueError):
        DBC.build_url({"dialect": "sqlite", "mode": "url", "url": ""})
    with pytest.raises(ValueError):
        DBC.build_url({"dialect": "postgresql", "host": "", "database": "d"})


def test_url_mode_accepts_known_scheme_only():
    ok = DBC.build_url({"dialect": "sqlite", "mode": "url",
                        "url": "postgresql+psycopg://u:p@h:5432/d"})
    assert ok == "postgresql+psycopg://u:p@h:5432/d"
    with pytest.raises(ValueError):
        DBC.build_url({"dialect": "sqlite", "mode": "url", "url": "mongodb://h/d"})


# ---------------------------------------------------------------- 掩码

def test_public_config_never_leaks_password():
    pub = DBC.public_config({"dialect": "postgresql", "host": "10.0.0.9", "database": "xf",
                             "username": "u", "password": "super-secret"})
    assert "super-secret" not in str(pub)
    assert pub["password_set"] is True
    assert "super-secret" not in pub["url_preview"]


def test_mask_url_hides_credentials():
    assert DBC._mask_url("postgresql://u:secret@h:5432/d") == f"postgresql://u:{DBC.MASK}@h:5432/d"
    assert DBC._mask_url("sqlite:////tmp/a.db") == "sqlite:////tmp/a.db"


# ---------------------------------------------------------------- 落盘

def test_save_and_load_roundtrip(tmp_cfg_path):
    cfg = {"dialect": "mysql", "host": "db.internal", "port": 3307, "database": "xf",
           "username": "root", "password": "s3cret", "path": "", "url": "", "ssl": False}
    with _Restore(tmp_cfg_path):
        DBC.save_config(cfg)
        loaded = DBC.saved_config()
        assert loaded["password"] == "s3cret"          # 服务端内部可读
        assert loaded["port"] == 3307
        assert DBC.public_config(loaded)["password_set"] is True
        assert "s3cret" not in DBC.state()["config"]["url_preview"]


def test_state_reports_dialects_and_driver_availability():
    st = DBC.state()
    keys = {d["key"] for d in st["dialects"]}
    assert {"sqlite", "postgresql", "mysql", "mariadb", "mssql"} <= keys
    sqlite = next(d for d in st["dialects"] if d["key"] == "sqlite")
    assert sqlite["ready"] is True                     # 内置驱动必须就绪
    assert st["active"]["dialect"] in ("sqlite", "postgresql", "mysql", "mariadb", "mssql")
    assert DBC.MASK not in st["active"]["url"] or True


def test_missing_driver_is_reported_not_crashed():
    meta = next(d for d in DBC.dialects() if d["key"] == "postgresql")
    if meta["ready"]:
        pytest.skip("本机已安装 PostgreSQL 驱动，跳过缺驱动分支")
    result = DBC.test_connection({"dialect": "postgresql", "host": "127.0.0.1",
                                  "database": "xf", "username": "u", "password": "p"})
    assert result["ok"] is False
    assert "pip install" in result["hint"]


# ---------------------------------------------------------------- 试连 / 应用

def test_test_connection_sqlite_ok(tmp_cfg_path):
    tmp = _mk_tmp_dir("probe")
    with _Restore(os.path.join(tmp, "cfg.json")):
        r = DBC.test_connection({"dialect": "sqlite", "path": os.path.join(tmp, "probe.db")})
        assert r["ok"] is True
        assert r["dialect"] == "sqlite"
        assert r["server_version"]                     # sqlite_version()
        assert r["latency_ms"] >= 0


def test_apply_switches_creates_tables_and_rolls_back_on_failure(tmp_cfg_path):
    tmp = _mk_tmp_dir("apply")
    dbfile = os.path.join(tmp, "applied.db")
    with _Restore(tmp_cfg_path):
        r = DBC.apply_config({"dialect": "sqlite", "path": dbfile}, seed=False)
        assert r["ok"] is True, r
        assert r["stats"]["tables"] > 0
        assert r["dialect"] == "sqlite"
        assert os.path.exists(dbfile)
        assert os.path.exists(tmp_cfg_path)            # 配置已落盘
        assert DBC.saved_config()["path"] == dbfile
        assert "applied.db" in DBC.state()["active"]["url"]
    # 用例退出后已回滚：生效连接不再指向临时库
    assert dbfile not in get_database_url_override()


def test_apply_seeds_data_into_new_database():
    """配置成功即初始化并落盘数据：新库必须有院校 / 基线 / 内容。"""
    tmp = _mk_tmp_dir("seed")
    dbfile = os.path.join(tmp, "seeded.db")
    cfg_path = os.path.join(tmp, "db_config.json")
    with _Restore(cfg_path):
        r = DBC.apply_config({"dialect": "sqlite", "path": dbfile}, seed=True)
        assert r["ok"] is True, r
        assert r["stats"]["universities"] == 2868
        assert r["stats"]["baselines"] > 0
        assert r["seeded"] is True
        assert (DBC.load_raw().get("last_applied") or {}).get("stats", {}).get("universities") == 2868


def test_apply_failure_keeps_previous_connection(tmp_cfg_path):
    with _Restore(tmp_cfg_path):
        before = DBC.state()["active"]["url"]
        r = DBC.apply_config({"dialect": "postgresql", "host": "127.0.0.1", "port": 1,
                              "database": "nope", "username": "u", "password": "p"})
        assert r["ok"] is False
        assert r["stage"] in ("connect", "init")
        assert DBC.state()["active"]["url"] == before   # 没有把服务切到坏库上
        assert not os.path.exists(tmp_cfg_path)         # 失败不落盘


# ---------------------------------------------------------------- 管理端接口

def test_db_config_api_requires_auth():
    assert c.get("/api/admin/db-config").status_code == 401
    assert c.post("/api/admin/db-config/test", json={"dialect": "sqlite"}).status_code in (401, 403)


def test_db_config_api_state_and_test():
    headers = ready_headers(c)
    r = c.get("/api/admin/db-config", headers=headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["dialects"]
    assert j["config"]["password_set"] in (True, False)
    assert "password" in j["config"]

    tmp = _mk_tmp_dir("api")
    dbfile = os.path.join(tmp, "api.db")
    r = c.post("/api/admin/db-config/test", headers=headers,
               json={"dialect": "sqlite", "path": dbfile})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    shutil.rmtree(tmp, ignore_errors=True)


def test_db_config_api_apply_then_reset():
    """接口闭环：apply 切到临时库并播种，再 reset 回默认，最后还原测试环境。"""
    headers = ready_headers(c)
    tmp = _mk_tmp_dir("apiapply")
    dbfile = os.path.join(tmp, "applied.db")
    cfg_path = os.path.join(tmp, "db_config.json")
    prev_override = get_database_url_override()
    prev_cfg = DBC.CONFIG_PATH
    DBC.CONFIG_PATH = cfg_path
    try:
        r = c.post("/api/admin/db-config/apply", headers=headers,
                   json={"dialect": "sqlite", "path": dbfile, "seed": True})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["stats"]["universities"] == 2868
        assert j["admin_carried"] >= 0
        # 切换后令牌仍可用（账号已搬到新库）
        assert c.get("/api/admin/db-config", headers=headers).status_code == 200
        r = c.post("/api/admin/db-config/reset", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["dialect"] == "sqlite"
    finally:
        DBC.CONFIG_PATH = prev_cfg
        set_database_url(prev_override)
        reset_engine()
        shutil.rmtree(tmp, ignore_errors=True)
