"""管理端安全加固测试（D2）：登录限流锁定、令牌失效、初始密码拦截、登录审计。"""
import uuid

import main
from fastapi.testclient import TestClient
from sqlalchemy import select

from db import session_scope
from db.models import AdminUser
from db.seed import hash_password

c = TestClient(main.app)

PWD = "init-pass-123"


def _make_user(must_change: bool = False, password: str = PWD) -> str:
    username = f"sec_{uuid.uuid4().hex[:8]}"
    pwd_hash, salt = hash_password(password)
    with session_scope() as s:
        s.add(AdminUser(username=username, password_hash=pwd_hash, salt=salt,
                        role="admin", must_change_password=must_change))
    return username


def _drop(username: str) -> None:
    with session_scope() as s:
        row = s.scalar(select(AdminUser).where(AdminUser.username == username))
        if row is not None:
            s.delete(row)


def _login(username: str, password: str = PWD):
    return c.post("/api/admin/login", json={"username": username, "password": password})


def test_lockout_after_max_failures():
    """连续 5 次错误 → 第 5 次直接 429，并给出 Retry-After；锁定期内正确密码也拒绝。"""
    u = _make_user()
    try:
        for i in range(4):
            r = _login(u, "wrong-pass")
            assert r.status_code == 401, f"第 {i + 1} 次应为 401，实际 {r.status_code}"
            assert r.json()["detail"] == "用户名或密码错误", "失败文案不应泄露账号是否存在"
        r = _login(u, "wrong-pass")
        assert r.status_code == 429, r.text
        assert int(r.headers.get("Retry-After", "0")) > 0
        blocked = _login(u, PWD)
        assert blocked.status_code == 429, "锁定期内即使密码正确也应拒绝"
        with session_scope() as s:
            row = s.scalar(select(AdminUser).where(AdminUser.username == u))
            assert row.failed_attempts >= 5 and row.locked_until is not None
    finally:
        _drop(u)


def test_success_resets_failure_counter():
    """成功登录清零计数：4 次失败后成功，再失败 4 次仍不应被锁。"""
    u = _make_user()
    try:
        for _ in range(4):
            assert _login(u, "wrong-pass").status_code == 401
        ok = _login(u, PWD)
        assert ok.status_code == 200
        for _ in range(4):
            assert _login(u, "wrong-pass").status_code == 401, "清零后不应立刻触发锁定"
        assert _login(u, PWD).status_code == 200
    finally:
        _drop(u)


def test_token_invalid_after_password_change():
    """改密后旧令牌立即失效；响应返回的新令牌可用。"""
    u = _make_user()
    try:
        token = _login(u, PWD).json()["token"]
        old = {"Authorization": f"Bearer {token}"}
        assert c.get("/api/admin/me", headers=old).status_code == 200

        changed = c.post("/api/admin/change-password",
                         json={"old_password": PWD, "new_password": "brand-new-456"}, headers=old)
        assert changed.status_code == 200, changed.text
        new_token = changed.json()["token"]

        assert c.get("/api/admin/me", headers=old).status_code == 401, "旧令牌必须失效"
        assert "密码已变更" in c.get("/api/admin/me", headers=old).json()["detail"]
        assert c.get("/api/admin/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
    finally:
        _drop(u)


def test_initial_password_blocks_writes():
    """仍用初始密码：读接口可用，写接口 403。"""
    u = _make_user(must_change=True)
    try:
        token = _login(u, PWD).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        me = c.get("/api/admin/me", headers=h)
        assert me.status_code == 200 and me.json()["user"]["must_change_password"] is True
        blocked = c.post("/api/admin/sync", json={"targets": ["content"]}, headers=h)
        assert blocked.status_code == 403
        assert "初始密码" in blocked.json()["detail"]
    finally:
        _drop(u)


def test_login_attempts_are_audited():
    """失败与成功都留审计；弱令牌被拒。"""
    u = _make_user()
    try:
        _login(u, "wrong-pass")
        _login(u, PWD)
        from tests.helpers import ready_headers
        rows = c.get("/api/admin/login-attempts", params={"limit": 50},
                     headers=ready_headers(c)).json()["rows"]
        mine = [r for r in rows if r["username"] == u]
        assert any(r["success"] is False and r["reason"] == "bad_credentials" for r in mine)
        assert any(r["success"] is True and r["reason"] == "ok" for r in mine)
        # 伪造签名
        forged = c.get("/api/admin/me", headers={"Authorization": "Bearer abc.def"})
        assert forged.status_code == 401
    finally:
        _drop(u)


def test_unknown_user_is_rate_limited_by_ip():
    """未知账号按 IP 限流：连续失败后返回 429，而不是无限试错。"""
    from services import admin_auth as auth
    name = f"ghost_{uuid.uuid4().hex[:6]}"
    # 用独立 IP 标记避免与其他用例共享桶（TestClient 默认 client.host=testclient）
    ip = f"10.0.0.{uuid.uuid4().int % 250 + 1}"
    for _ in range(auth.LOGIN_MAX_FAILS):
        r = auth.login(name, "x", ip=ip)
        assert r["ok"] is False
    out = auth.login(name, "x", ip=ip)
    assert out["reason"] == "locked" and out["retry_after"] > 0
