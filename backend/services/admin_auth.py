"""管理端鉴权：PBKDF2 密码校验 + HMAC 签名令牌 + 登录限流锁定（无第三方 JWT 依赖）。

安全要点（D2）：
- 连续失败 N 次锁定一段时间，失败/成功都写 `login_attempts` 审计；
- 令牌内嵌 `pwd`（密码变更时间戳），改密后旧令牌立即失效；
- `require_admin_ready` 在「仍用初始密码」时拒绝写操作，避免默认口令下被改数据。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import func, select

from db.database import session_scope
from db.models import AdminUser, LoginAttempt, Setting
from db.seed import hash_password, verify_password

TOKEN_TTL = int(os.environ.get("XUEFENG_TOKEN_TTL", "43200"))  # 默认 12 小时
# 登录限流：窗口内失败达到上限即锁定（可按部署环境用环境变量调整）
LOGIN_MAX_FAILS = int(os.environ.get("XUEFENG_LOGIN_MAX_FAILS", "5"))
LOGIN_WINDOW = int(os.environ.get("XUEFENG_LOGIN_WINDOW", "300"))      # 失败统计窗口（秒）
LOGIN_LOCK = int(os.environ.get("XUEFENG_LOGIN_LOCK", "900"))          # 锁定时长（秒）
_secret_cache: tuple[float, bytes] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite 读回的 DateTime 可能是 naive，统一按 UTC 解释，避免比较报错。"""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _secret() -> bytes:
    global _secret_cache
    now = time.time()
    if _secret_cache and now - _secret_cache[0] < 300:
        return _secret_cache[1]
    env = os.environ.get("XUEFENG_AUTH_SECRET")
    if env:
        value = env.encode()
    else:
        with session_scope() as s:
            row = s.get(Setting, "auth_secret")
            if row is None:
                row = Setting(key="auth_secret", value=secrets.token_urlsafe(48))
                s.add(row)
                s.flush()
            value = row.value.encode()
    _secret_cache = (now, value)
    return value


def password_stamp(user: AdminUser) -> int:
    """密码版本标记：改密时间（未改过则退化为建号时间），用于令牌失效判定。

    用微秒精度：同一秒内登录再改密也能区分，否则旧令牌会被误判为仍然有效。
    """
    base = _aware(user.password_changed_at) or _aware(user.created_at) or _now()
    return int(base.timestamp() * 1_000_000)


def create_token(username: str, role: str = "admin", pwd: int | None = None) -> dict:
    payload = {"sub": username, "role": role, "exp": int(time.time()) + TOKEN_TTL,
               "nonce": secrets.token_hex(4)}
    if pwd is not None:
        payload["pwd"] = int(pwd)
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return {"token": f"{body}.{sig}", "expires_in": TOKEN_TTL,
            "expires_at": payload["exp"]}


def decode_token(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="令牌格式错误")
    expect = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        raise HTTPException(status_code=401, detail="令牌签名无效")
    try:
        payload = json.loads(_b64d(body))
    except Exception:
        raise HTTPException(status_code=401, detail="令牌内容无效")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return payload


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI 依赖：校验 Authorization: Bearer <token>，并确认令牌未因改密而失效。"""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录或缺少令牌")
    payload = decode_token(token)
    username = payload.get("sub", "")
    with session_scope() as s:
        user = s.scalar(select(AdminUser).where(AdminUser.username == username))
        if user is None:
            raise HTTPException(status_code=401, detail="账号不存在或已停用")
        current = password_stamp(user)
    # 老令牌没有 pwd 字段 → 视为过期，强制重新登录
    if int(payload.get("pwd", -1)) != current:
        raise HTTPException(status_code=401, detail="密码已变更，请重新登录")
    return {"username": username, "role": payload.get("role", "admin")}


def require_admin_ready(admin: dict = Depends(require_admin)) -> dict:
    """写操作用依赖：仍未修改初始密码时拒绝，避免默认口令直接改数据。"""
    profile = admin_profile(admin["username"])
    if profile.get("must_change_password"):
        raise HTTPException(status_code=403, detail="请先修改初始密码，再进行数据写操作")
    return admin


def require_admin_flexible(authorization: str | None = Header(default=None),
                           token: str | None = Query(default=None)) -> dict:
    """导出下载用：允许 ?token= 查询参数（浏览器直接下载无法带 header）。"""
    return require_admin(authorization or (f"Bearer {token}" if token else None))


# ---------------------------------------------------------------- 登录

def _record(s, username: str, ip: str, success: bool, reason: str, ua: str = "") -> None:
    s.add(LoginAttempt(username=username[:64], ip=(ip or "")[:64], success=success,
                       reason=reason[:32], user_agent=(ua or "")[:255]))


def _ip_failures(s, ip: str) -> int:
    """同 IP 在窗口内的失败次数（未知账号限流用）。"""
    if not ip:
        return 0
    since = _now() - timedelta(seconds=LOGIN_WINDOW)
    return int(s.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.ip == ip, LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since)) or 0)


def login(username: str, password: str, ip: str = "", user_agent: str = "") -> dict:
    """校验账号密码并记录审计；返回 {ok, user|reason, retry_after?}。

    判定顺序：账号锁定 → 密码校验 → 失败计数/触发锁定 → 成功清零。
    未知账号按 IP 失败数限流，避免被用来无成本试错。
    """
    username = (username or "").strip()
    now = _now()
    with session_scope() as s:
        user = s.scalar(select(AdminUser).where(AdminUser.username == username))

        if user is None:
            fails = _ip_failures(s, ip)
            if fails >= LOGIN_MAX_FAILS:
                _record(s, username, ip, False, "locked", user_agent)
                return {"ok": False, "reason": "locked", "retry_after": LOGIN_WINDOW,
                        "detail": f"失败次数过多，请 {LOGIN_WINDOW // 60} 分钟后再试"}
            _record(s, username, ip, False, "bad_credentials", user_agent)
            return {"ok": False, "reason": "bad_credentials", "detail": "用户名或密码错误"}

        locked_until = _aware(user.locked_until)
        if locked_until and locked_until > now:
            retry = max(1, int((locked_until - now).total_seconds()))
            _record(s, username, ip, False, "locked", user_agent)
            return {"ok": False, "reason": "locked", "retry_after": retry,
                    "detail": f"账号已锁定，请 {math.ceil(retry / 60)} 分钟后再试"}
        if locked_until:
            # 锁定期已过但计数还停在阈值上：不清零的话，解锁后只要再输错一次
            # 就会立刻重新锁定 15 分钟，正确密码也进不来（实测过的坑）。
            user.failed_attempts = 0
            user.locked_until = None

        if not verify_password(password, user.password_hash, user.salt):
            user.failed_attempts = int(user.failed_attempts or 0) + 1
            if user.failed_attempts >= LOGIN_MAX_FAILS:
                user.locked_until = now + timedelta(seconds=LOGIN_LOCK)
                _record(s, username, ip, False, "locked", user_agent)
                return {"ok": False, "reason": "locked", "retry_after": LOGIN_LOCK,
                        "detail": f"失败次数过多，账号已锁定 {math.ceil(LOGIN_LOCK / 60)} 分钟"}
            _record(s, username, ip, False, "bad_credentials", user_agent)
            # 文案与「账号不存在」保持一致，避免通过提示差异枚举账号
            return {"ok": False, "reason": "bad_credentials", "detail": "用户名或密码错误"}

        # 成功：清零失败计数与锁定状态
        user.failed_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        _record(s, username, ip, True, "ok", user_agent)
        return {"ok": True, "user": {"username": user.username, "role": user.role,
                                     "must_change_password": user.must_change_password},
                "pwd": password_stamp(user)}


def change_password(username: str, old_password: str, new_password: str, ip: str = "") -> dict:
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    if new_password == old_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")
    with session_scope() as s:
        user = s.scalar(select(AdminUser).where(AdminUser.username == username))
        if user is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        if not verify_password(old_password, user.password_hash, user.salt):
            raise HTTPException(status_code=400, detail="原密码不正确")
        pwd_hash, salt = hash_password(new_password)
        user.password_hash = pwd_hash
        user.salt = salt
        user.must_change_password = False
        user.password_changed_at = _now()
        user.failed_attempts = 0
        user.locked_until = None
        _record(s, username, ip, True, "password_changed")
        stamp = password_stamp(user)
    return {"ok": True, "pwd": stamp}


def admin_profile(username: str) -> dict:
    with session_scope() as s:
        user = s.scalar(select(AdminUser).where(AdminUser.username == username))
        if user is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        locked_until = _aware(user.locked_until)
        return {
            "username": user.username, "role": user.role,
            "must_change_password": user.must_change_password,
            "failed_attempts": int(user.failed_attempts or 0),
            "locked_until": locked_until.isoformat() if locked_until and locked_until > _now() else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "password_changed_at": (user.password_changed_at.isoformat()
                                    if user.password_changed_at else None),
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }


def recent_attempts(limit: int = 50) -> list[dict]:
    """最近登录审计（管理端可查，不含密码）。"""
    with session_scope() as s:
        rows = s.scalars(select(LoginAttempt).order_by(LoginAttempt.id.desc()).limit(limit)).all()
        return [{"id": r.id, "username": r.username, "ip": r.ip, "success": r.success,
                 "reason": r.reason, "created_at": r.created_at.isoformat() if r.created_at else None}
                for r in rows]
