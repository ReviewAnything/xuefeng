"""管理端 + 数据落库测试（FastAPI TestClient）。"""
import uuid

import main
from fastapi.testclient import TestClient
from sqlalchemy import select

from db import repository as repo
from db import session_scope
from db.models import AdminUser
from db.seed import hash_password, verify_password

c = TestClient(main.app)


def _login(username: str = "admin", password: str = "xuefeng@2026") -> str:
    r = c.post("/api/admin/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {_login()}"}


def test_admin_requires_auth():
    assert c.get("/api/admin/overview").status_code == 401
    assert c.get("/api/admin/universities").status_code == 401


def test_admin_login_rejects_wrong_password():
    r = c.post("/api/admin/login", json={"username": "admin", "password": "wrong-pass"})
    assert r.status_code == 401


def test_admin_overview_kpis():
    r = c.get("/api/admin/overview", headers=_auth())
    assert r.status_code == 200
    j = r.json()
    assert j["kpis"]["universities"] == 2868
    assert j["kpis"]["benke"] == 1308 and j["kpis"]["zhuanke"] == 1560
    assert j["kpis"]["elite_211"] == 112
    assert len(j["trend"]) == 14
    assert any(ch["key"] == "db" and ch["status"] == "ok" for ch in j["checks"])


def test_admin_universities_pagination():
    h = _auth()
    r = c.get("/api/admin/universities", params={"page": 2, "page_size": 10}, headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j["page"] == 2 and j["page_size"] == 10
    assert j["total_matched"] == 2868
    assert len(j["universities"]) == 10
    r2 = c.get("/api/admin/universities", params={"q": "清华"}, headers=h)
    assert r2.json()["total_matched"] >= 1


def test_admin_baselines_official_rows():
    h = _auth()
    r = c.get("/api/admin/baselines", params={"province": "河南", "subject": "物理类"}, headers=h)
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 5
    official = [x for x in rows if x["data_source"] == "official"]
    assert len(official) == 5     # 河南物理：985/211/一本/二本/专科 均为官方覆盖
    yiben = next(x for x in rows if x["tier"] == "普通一本")
    assert yiben["min_rank"] == 130195


def test_database_repository_matches_json():
    counts = repo.university_counts()
    assert counts["total"] == 2868
    assert counts["count_985"] == 38 and counts["count_211"] == 112
    names = repo.elite_names("985")
    assert len(names) == 39 and "清华大学" in names


def test_admin_sync_is_idempotent():
    h = _auth()
    first = c.post("/api/admin/sync", json={"targets": ["content"], "force": True}, headers=h)
    assert first.status_code == 200, first.text
    assert first.json()["job_id"] > 0
    second = c.post("/api/admin/sync", json={"targets": ["content"]}, headers=h)
    assert second.status_code == 200
    jobs = c.get("/api/admin/jobs", headers=h).json()["rows"]
    assert jobs and jobs[0]["kind"] == "content"


def test_admin_change_password_for_temp_user():
    username = f"pytest_{uuid.uuid4().hex[:8]}"
    pwd_hash, salt = hash_password("init-pass-123")
    with session_scope() as s:
        s.add(AdminUser(username=username, password_hash=pwd_hash, salt=salt,
                        role="admin", must_change_password=True))
    token = _login(username, "init-pass-123")
    h = {"Authorization": f"Bearer {token}"}
    bad = c.post("/api/admin/change-password",
                 json={"old_password": "wrong", "new_password": "new-pass-456"}, headers=h)
    assert bad.status_code == 400
    ok = c.post("/api/admin/change-password",
                json={"old_password": "init-pass-123", "new_password": "new-pass-456"}, headers=h)
    assert ok.status_code == 200
    with session_scope() as s:
        row = s.scalar(select(AdminUser).where(AdminUser.username == username))
        assert verify_password("new-pass-456", row.password_hash, row.salt)
        assert row.must_change_password is False
        s.delete(row)


def test_admin_events_and_export():
    h = _auth()
    assert c.get("/api/admin/events", headers=h).status_code == 200
    r = c.get("/api/admin/export/universities.csv", headers=h)
    assert r.status_code == 200
    assert r.content[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM，Excel 直接打开不乱码
    assert "校名" in r.content.decode("utf-8") and "清华大学" in r.content.decode("utf-8")


def test_admin_sources_status():
    j = c.get("/api/admin/sources", headers=_auth()).json()
    assert j["ok"] is True
    keys = {f["key"] for f in j["files"]}
    assert {"universities", "elite", "baseline", "official", "content"} <= keys
    assert all(f["exists"] for f in j["files"])
