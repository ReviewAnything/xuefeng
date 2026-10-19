"""幂等播种：把 JSON 数据源灌入数据库。

设计要点：
  - 以源文件 SHA-256 作为签名，签名未变则跳过，避免每次启动重复写库；
  - 同一 (省, 科类, 批次) 只保留一行，官方值覆盖估算值并标注 data_source；
  - 所有写入可重复执行（upsert），不会产生重复数据。
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .database import session_scope
from .models import (AdminUser, AdmissionBaseline, EliteUniversity, Major,
                     Resource, Setting, University)

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
SHARED_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
TARGETS = ("universities", "admission", "content", "admin")

DEFAULT_ADMIN_USER = os.environ.get("XUEFENG_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("XUEFENG_ADMIN_PASSWORD", "xuefeng@2026")


# ---------------------------------------------------------------- 工具函数

def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _signature(*paths: str) -> str:
    h = hashlib.sha256()
    for p in paths:
        if os.path.exists(p):
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:32]


def _get_setting(session, key: str) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else None


def _set_setting(session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


def _empty_stat() -> dict:
    return {"total": 0, "inserted": 0, "updated": 0, "skipped": 0}


# ---------------------------------------------------------------- 各目标同步

def sync_universities(session) -> dict:
    """教育部全国普通高校名单 → universities 表。"""
    path = os.path.join(DATA_DIR, "universities_national.json")
    data = _read_json(path)
    items = data["universities"]
    existing = {u.name: u for u in session.scalars(select(University)).all()}
    stat = _empty_stat()
    stat["total"] = len(items)
    for it in items:
        row = existing.get(it["name"])
        payload = {
            "province": it.get("province") or "",
            "city": it.get("city") or "",
            "level": it.get("level") or "",
            "nature": it.get("nature") or "",
            "supervisor": it.get("supervisor") or "",
            "code": it.get("code") or "",
            "category": it.get("category") or "",
            "is_985": bool(it.get("is_985")),
            "is_211": bool(it.get("is_211")),
            "is_dfc": bool(it.get("is_dfc")),
            "website": it.get("website") or "",
            "source": "moe",
        }
        if row is None:
            session.add(University(name=it["name"], **payload))
            stat["inserted"] += 1
        else:
            changed = any(getattr(row, k) != v for k, v in payload.items())
            if changed:
                for k, v in payload.items():
                    setattr(row, k, v)
                stat["updated"] += 1
            else:
                stat["skipped"] += 1
    session.flush()
    return stat


def sync_elite(session) -> dict:
    """985/211 权威清单（112 所，含军校/拆分校区）→ elite_universities 表。"""
    path = os.path.join(DATA_DIR, "universities.json")
    data = _read_json(path)
    items = data["universities"]
    existing = {u.name: u for u in session.scalars(select(EliteUniversity)).all()}
    stat = _empty_stat()
    stat["total"] = len(items)
    for it in items:
        row = existing.get(it["name"])
        payload = {
            "short": it.get("short") or "",
            "province": it.get("province") or "",
            "city": it.get("city") or "",
            "category": it.get("category") or "",
            "supervisor": it.get("supervisor") or "",
            "is_985": bool(it.get("is_985")),
            "is_211": bool(it.get("is_211")),
            "is_dfc": bool(it.get("is_dfc")),
        }
        if row is None:
            session.add(EliteUniversity(name=it["name"], **payload))
            stat["inserted"] += 1
        else:
            changed = any(getattr(row, k) != v for k, v in payload.items())
            if changed:
                for k, v in payload.items():
                    setattr(row, k, v)
                stat["updated"] += 1
            else:
                stat["skipped"] += 1
    session.flush()
    return stat


def sync_admission(session) -> dict:
    """31 省估算基线 + 6 省官方覆盖层 → admission_baselines 表（单行合并）。"""
    baseline = _read_json(os.path.join(DATA_DIR, "admission_real_baseline.json"))
    official_path = os.path.join(DATA_DIR, "admission_official_2024.json")
    official = _read_json(official_path) if os.path.exists(official_path) else {}

    tier_order = baseline.get("tier_order", [])
    base_year = int(baseline.get("meta", {}).get("year") or 0)
    off_year = int(official.get("meta", {}).get("year") or 0)
    sources = official.get("meta", {}).get("sources", {})
    batch_lines = official.get("batch_lines", {})
    school_lines = official.get("school_tier_lines", {})

    existing = {(r.province, r.subject, r.tier): r
                for r in session.scalars(select(AdmissionBaseline)).all()}
    stat = _empty_stat()
    seen = set()

    for province, subjects in baseline.get("tier_baseline", {}).items():
        for subject, tiers in subjects.items():
            for tier, base in tiers.items():
                key = (province, subject, tier)
                seen.add(key)
                payload = {
                    "min_score": int(base.get("min_score") or 0),
                    "min_rank": int(base.get("min_rank") or 0),
                    "data_source": "estimated",
                    "line": "",
                    "school": "",
                    "year": base_year,
                    "source_url": "",
                }
                ov = batch_lines.get(province, {}).get(subject, {}).get(tier)
                sv = school_lines.get(province, {}).get(subject, {}).get(tier) if tier in ("985", "211") else None
                if ov:
                    payload.update({
                        "min_score": int(ov.get("score") or 0),
                        "min_rank": int(ov.get("rank") or 0),
                        "data_source": "official",
                        "line": ov.get("line") or "",
                        "year": off_year or base_year,
                        "source_url": sources.get(province, ""),
                    })
                elif sv:
                    payload.update({
                        "min_score": int(sv.get("score") or 0),
                        "min_rank": int(sv.get("rank") or 0),
                        "data_source": "official",
                        "line": sv.get("line") or "",
                        "school": sv.get("school") or "",
                        "year": off_year or base_year,
                        "source_url": sources.get(province, ""),
                    })
                row = existing.get(key)
                if row is None:
                    session.add(AdmissionBaseline(province=province, subject=subject, tier=tier, **payload))
                    stat["inserted"] += 1
                else:
                    changed = any(getattr(row, k) != v for k, v in payload.items())
                    if changed:
                        for k, v in payload.items():
                            setattr(row, k, v)
                        stat["updated"] += 1
                    else:
                        stat["skipped"] += 1
                stat["total"] += 1

    # 清理已不存在于数据源的旧行（例如省份口径调整）
    for key, row in existing.items():
        if key not in seen:
            session.delete(row)

    _set_setting(session, "tier_order", json.dumps(tier_order, ensure_ascii=False))
    _set_setting(session, "admission_meta", json.dumps(baseline.get("meta", {}), ensure_ascii=False))
    _set_setting(session, "official_meta", json.dumps(official.get("meta", {}), ensure_ascii=False))
    _set_setting(session, "official_coverage", json.dumps(official.get("meta", {}).get("coverage", []), ensure_ascii=False))
    session.flush()
    return stat


def sync_content(session) -> dict:
    """专业图谱 + 开源资源 → majors / resources 表。"""
    data = _read_json(os.path.join(SHARED_DIR, "content.json"))
    stat = _empty_stat()

    majors = data.get("MAJORS", [])
    existing = {m.name: m for m in session.scalars(select(Major)).all()}
    for it in majors:
        payload = {
            "cat": it.get("cat") or "",
            "view": it.get("view") or "recommend",
            "reason": it.get("reason") or "",
            "bias": it.get("bias") or "",
            "tags": json.dumps(it.get("tags") or [], ensure_ascii=False),
            "verify": it.get("verify") or "",
        }
        row = existing.get(it["name"])
        if row is None:
            session.add(Major(name=it["name"], **payload))
            stat["inserted"] += 1
        else:
            changed = any(getattr(row, k) != v for k, v in payload.items())
            if changed:
                for k, v in payload.items():
                    setattr(row, k, v)
                stat["updated"] += 1
            else:
                stat["skipped"] += 1
        stat["total"] += 1

    resources = data.get("RESOURCES", [])
    existing_r = {r.name: r for r in session.scalars(select(Resource)).all()}
    for it in resources:
        payload = {
            "cat": it.get("cat") or "",
            "lic": it.get("lic") or "",
            "meta": it.get("meta") or "",
            "desc": it.get("desc") or "",
            "links": json.dumps(it.get("links") or [], ensure_ascii=False),
        }
        row = existing_r.get(it["name"])
        if row is None:
            session.add(Resource(name=it["name"], **payload))
            stat["inserted"] += 1
        else:
            changed = any(getattr(row, k) != v for k, v in payload.items())
            if changed:
                for k, v in payload.items():
                    setattr(row, k, v)
                stat["updated"] += 1
            else:
                stat["skipped"] += 1
        stat["total"] += 1

    _set_setting(session, "content_meta", json.dumps({
        "APP_VERSION": data.get("APP_VERSION", ""),
        "DATA_DATE": data.get("DATA_DATE", ""),
        "NOTE": data.get("NOTE", ""),
    }, ensure_ascii=False))
    session.flush()
    return stat


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256（20 万次迭代）。"""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return dk.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    calc, _ = hash_password(password, salt)
    return secrets.compare_digest(calc, password_hash)


def ensure_admin(session) -> dict:
    """确保管理员账号与鉴权密钥存在（不覆盖已改过的密码）。"""
    stat = {"created": 0, "existing": 0}
    user = session.scalar(select(AdminUser).where(AdminUser.username == DEFAULT_ADMIN_USER))
    if user is None:
        pwd_hash, salt = hash_password(DEFAULT_ADMIN_PASSWORD)
        session.add(AdminUser(username=DEFAULT_ADMIN_USER, password_hash=pwd_hash, salt=salt,
                              role="admin", must_change_password=True))
        stat["created"] = 1
    else:
        stat["existing"] = 1
    if _get_setting(session, "auth_secret") is None:
        _set_setting(session, "auth_secret", secrets.token_urlsafe(48))
    session.flush()
    return stat


# ---------------------------------------------------------------- 对外入口

def _run(session, targets: list[str]) -> dict:
    result = {}
    if "universities" in targets:
        result["universities"] = sync_universities(session)
        result["elite"] = sync_elite(session)
    if "admission" in targets:
        result["admission"] = sync_admission(session)
    if "content" in targets:
        result["content"] = sync_content(session)
    if "admin" in targets:
        ensure_admin(session)
        result["admin"] = {"total": 1, "inserted": 0, "updated": 0, "skipped": 1}
    return result


def sync_all(targets: list[str] | None = None, force: bool = False) -> dict:
    """执行同步（管理端调用，force=True 时忽略签名强制重灌）。"""
    targets = [t for t in (targets or list(TARGETS)) if t in TARGETS]
    started = time.time()
    stats: dict = {}
    with session_scope() as session:
        for target in targets:
            sig_key = f"seed_sig:{target}"
            if target == "universities":
                sig = _signature(os.path.join(DATA_DIR, "universities_national.json"),
                                 os.path.join(DATA_DIR, "universities.json"))
            elif target == "admission":
                sig = _signature(os.path.join(DATA_DIR, "admission_real_baseline.json"),
                                 os.path.join(DATA_DIR, "admission_official_2024.json"))
            elif target == "content":
                sig = _signature(os.path.join(SHARED_DIR, "content.json"))
            else:
                sig = "-"
            if not force and _get_setting(session, sig_key) == sig:
                stats[target] = {"total": 0, "inserted": 0, "updated": 0, "skipped": 0,
                                 "note": "签名未变化，已跳过"}
                continue
            partial = _run(session, [target])
            stats.update(partial)
            if target != "admin":
                _set_setting(session, sig_key, sig)
            stats.setdefault(target, {"total": 0, "inserted": 0, "updated": 0, "skipped": 0})
    stats["duration_ms"] = int((time.time() - started) * 1000)
    return stats


def ensure_seeded() -> dict:
    """启动时调用：仅在数据缺失或源文件变化时播种。"""
    try:
        return sync_all(force=False)
    except Exception as exc:  # 播种失败不应导致服务无法启动
        return {"error": f"{type(exc).__name__}: {exc}"}
