"""可观测性与备份测试（D3）：request id、访问指标、健康检查、SQLite 一致性备份。"""
import importlib.util
import os
import sqlite3

import main
from fastapi.testclient import TestClient

from services import observability as OBS

c = TestClient(main.app)


def test_health_exposes_runtime_and_data_state():
    c.get("/api/content")  # 预热：让中间件先记录一次请求（health 的快照不含自身）
    j = c.get("/api/health").json()
    assert j["status"] == "ok"
    assert j["database"]["size_kb"] >= 0
    assert "active_year" in j and j["active_year"]
    assert set(j["school_lines"]) == {"total", "years"}
    obs = j["observability"]
    assert obs["requests"] >= 1 and obs["slow_threshold_ms"] > 0
    assert isinstance(obs["recent"], list) and len(obs["recent"]) <= 5


def test_request_id_is_echoed_or_generated():
    r = c.get("/api/content", headers={"X-Request-ID": "trace-abc"})
    assert r.headers.get("X-Request-ID") == "trace-abc"
    r2 = c.get("/api/content")
    assert len(r2.headers.get("X-Request-ID", "")) >= 8


def test_metrics_count_requests_and_errors():
    before = OBS.snapshot()["requests"]
    c.get("/api/majors")
    c.get("/api/links-not-exist")
    after = OBS.snapshot()
    assert after["requests"] >= before + 2
    assert after["avg_ms"] >= 0
    # 404 不算 5xx，但请求必须被记录
    assert any(rec["path"] == "/api/links-not-exist" for rec in after["recent"])


def test_slow_requests_are_flagged(monkeypatch):
    monkeypatch.setattr(OBS, "SLOW_MS", 0)   # 阈值降到 0，任何请求都算慢
    before = OBS.snapshot()["slow"]
    c.get("/api/health")
    assert OBS.snapshot()["slow"] > before


def _load_backup_module():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "backup_db.py"))
    spec = importlib.util.spec_from_file_location("xuefeng_backup_db", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backup_creates_consistent_copy(tmp_path, monkeypatch):
    src = tmp_path / "src.db"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE t (x INTEGER)")
    con.executemany("INSERT INTO t (x) VALUES (?)", [(i,) for i in range(50)])
    con.commit()
    con.close()

    monkeypatch.setenv("XUEFENG_DB_PATH", str(src))
    mod = _load_backup_module()
    out = mod.backup(str(tmp_path / "bk"), keep=3, compress=False)

    assert out["ok"] and os.path.exists(out["backup"])
    copy = sqlite3.connect(out["backup"])
    assert copy.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    copy.close()


def test_backup_gzip_and_keep(tmp_path, monkeypatch):
    src = tmp_path / "src.db"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE t (x INTEGER)")
    con.commit()
    con.close()

    monkeypatch.setenv("XUEFENG_DB_PATH", str(src))
    mod = _load_backup_module()
    out = mod.backup(str(tmp_path / "bk"), keep=1, compress=True)
    assert out["backup"].endswith(".db.gz")
    assert os.path.getsize(out["backup"]) > 0
    assert len(out["kept"]) <= 1
