"""管理端 + 数据落库测试（FastAPI TestClient）。"""
import uuid

import main
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from db import repository as repo
from db import session_scope
from db.models import AdminUser, LoginAttempt
from db.seed import hash_password, verify_password
from tests.helpers import ready_headers

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
    # 用不存在的账号验证 401；同时清掉本机 IP 的历史失败记录，
    # 避免跨轮次累积触发 D2 的 IP 限流（限流逻辑由 test_admin_security 专门覆盖）
    with session_scope() as s:
        s.execute(delete(LoginAttempt).where(LoginAttempt.ip == "testclient"))
    r = c.post("/api/admin/login", json={"username": "no_such_admin", "password": "wrong-pass"})
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
    # M13/M14 校准后：官方省控线行分数来自 2026 官方控线（河南物理一本 513），
    # min_rank 保留 estimated 基线位次（不置 0，避免拉垮实时排名）；
    # 基线位次已改由同年真实一分段表反查（不再用模型推算值）
    assert yiben["min_score"] == 513
    assert yiben["min_rank"] == 130195


def test_database_repository_matches_json():
    counts = repo.university_counts()
    assert counts["total"] == 2868
    assert counts["count_985"] == 38 and counts["count_211"] == 112
    names = repo.elite_names("985")
    assert len(names) == 39 and "清华大学" in names


def test_admin_sync_is_idempotent():
    """同步按目标逐个留痕：重复执行不产生重复数据，只新增任务记录。"""
    h = ready_headers(c)
    first = c.post("/api/admin/sync", json={"targets": ["content"], "force": True}, headers=h)
    assert first.status_code == 200, first.text
    assert first.json()["results"]["content"]["job_id"] > 0
    second = c.post("/api/admin/sync", json={"targets": ["content"]}, headers=h)
    assert second.status_code == 200
    assert second.json()["results"]["content"]["ok"] is True
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


def test_admin_console_template_is_browser_safe():
    """回归：in-DOM 模板里自闭合自定义标签会被浏览器当成开标签，吞掉后续兄弟节点。

    曾导致登录页只剩账号输入框（密码框被吞进第一个 el-input 的插槽里）。
    """
    import re
    from pathlib import Path

    html = Path(__file__).resolve().parents[1] / "admin" / "index.html"
    src = html.read_text(encoding="utf-8")
    bad = re.findall(r"<(?:el|app)-[a-z0-9-]+[^<>]*/>", src)
    assert not bad, f"存在自闭合自定义标签，浏览器解析会吞掉后续节点: {bad[:5]}"

    # 登录表单必须同时存在账号与密码输入
    assert 'v-model="loginForm.username"' in src
    assert 'v-model="loginForm.password"' in src
    assert 'type="password"' in src

    # 每个自定义组件开标签都必须有对应闭合标签
    for tag in ("el-input", "el-table-column", "el-option", "app-icon", "el-input-number"):
        opened = len(re.findall(rf"<{tag}(?=[\s>])", src))
        closed = src.count(f"</{tag}>")
        assert opened == closed and opened > 0, f"{tag} 开闭标签数量不一致: {opened} vs {closed}"


def test_admin_console_served():
    r = c.get("/admin/")
    assert r.status_code == 200
    body = r.text
    assert "loginForm.password" in body and 'type="password"' in body


def test_admin_sync_targets_catalog_includes_pipelines():
    j = c.get("/api/admin/sync/targets", headers=_auth()).json()
    assert j["ok"] is True
    assert {"universities", "admission", "content"} <= set(j["seed_targets"])
    assert {"ingest_baseline", "build_universities"} <= set(j["pipeline_targets"])
    pipe = j["targets"]["ingest_baseline"]
    assert pipe["kind"] == "pipeline"
    assert pipe["then_seed"] == ["admission"]
    assert pipe["script"].endswith("ingest_gaokao_advisor.py")
    assert "last" in pipe


def test_admin_sync_seed_target_records_job():
    h = ready_headers(c)
    r = c.post("/api/admin/sync", json={"targets": ["content"], "force": True}, headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["results"]["content"]["ok"] is True
    assert j["results"]["content"]["job_id"] > 0
    rows = c.get("/api/admin/jobs?limit=10", headers=h).json()["rows"]
    hit = next(x for x in rows if x["kind"] == "content")
    assert hit["status"] == "success"
    assert hit["duration_ms"] is not None


def test_admin_sync_rejects_unknown_target():
    r = c.post("/api/admin/sync", json={"targets": ["nope"]}, headers=ready_headers(c))
    assert r.status_code == 400
