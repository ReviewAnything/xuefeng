"""测试共用：确保存在一个「已改密」的管理员，用于调用写接口。

D2 之后，仍使用初始密码的账号会被 `require_admin_ready` 拒绝写操作，
所以写接口相关测试需要一个 must_change_password=False 的账号。
"""
from __future__ import annotations

from sqlalchemy import select

from db.database import session_scope
from db.models import AdminUser
from db.seed import hash_password

READY_USER = "pytest_ready"
READY_PWD = "ready-pass-123"


def ensure_ready_admin() -> str:
    """幂等创建/修复测试用管理员，返回用户名。"""
    with session_scope() as s:
        row = s.scalar(select(AdminUser).where(AdminUser.username == READY_USER))
        if row is None:
            pwd_hash, salt = hash_password(READY_PWD)
            s.add(AdminUser(username=READY_USER, password_hash=pwd_hash, salt=salt,
                            role="admin", must_change_password=False))
        else:
            row.must_change_password = False
            row.failed_attempts = 0
            row.locked_until = None
    return READY_USER


def ready_headers(client) -> dict:
    """登录测试管理员，返回 Authorization 头。"""
    username = ensure_ready_admin()
    r = client.post("/api/admin/login", json={"username": username, "password": READY_PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
