"""管理端鉴权：PBKDF2 密码校验 + HMAC 签名令牌（无第三方 JWT 依赖）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import Header, HTTPException, Query
from sqlalchemy import select

from db.database import session_scope
from db.models import AdminUser, Setting
from db.seed import hash_password, verify_password

TOKEN_TTL = int(os.environ.get("XUEFENG_TOKEN_TTL", "43200"))  # 默认 12 小时
_secret_cache: tuple[float, bytes] | None = None


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


def create_token(username: str, role: str = "admin") -> dict:
    payload = {"sub": username, "role": role, "exp": int(time.time()) + TOKEN_TTL,
               "nonce": secrets.token_hex(4)}
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
    """FastAPI 依赖：校验 Authorization: Bearer <token>。"""
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录或缺少令牌")
    payload = decode_token(token)
    return {"username": payload["sub"], "role": payload.get("role", "admin")}


def require_admin_flexible(authorization: str | None = Header(default=None),
                           token: str | None = Query(default=None)) -> dict:
    """导出下载用：允许 ?token= 查询参数（浏览器直接下载无法带 header）。"""
    return require_admin(authorization or (f"Bearer {token}" if token else None))


def authenticate(username: str, password: str) -> dict | None:
    with session_scope() as s:
        user = s.scalar(select(AdminUser).where(AdminUser.username == username))
        if user is None:
            return None
        if not verify_password(password, user.password_hash, user.salt):
            return None
        user.last_login_at = datetime.now(timezone.utc)
        return {"username": user.username, "role": user.role,
                "must_change_password": user.must_change_password}


def change_password(username: str, old_password: str, new_password: str) -> dict:
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
    return {"ok": True}


def admin_profile(username: str) -> dict:
    with session_scope() as s:
        user = s.scalar(select(AdminUser).where(AdminUser.username == username))
        if user is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return {
            "username": user.username, "role": user.role,
            "must_change_password": user.must_change_password,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
